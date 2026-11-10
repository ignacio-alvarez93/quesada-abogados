"""WO-DV25-P3B3: security and idempotency before Box REAL (H1-H8).

Every test runs on TemporaryDirectory databases and folders only:

- ``SandboxMixin`` fails closed: ``sqlite3.connect`` itself refuses any database outside the
  sandbox (plain paths and ``file:`` URIs), ``connection.DB_PATH`` and ``expedient_service.DB_PATH``
  point to the sandbox, and the habitual ``quesada.db`` (+ journal/WAL) is fingerprinted by size,
  mtime AND SHA-256 before and after each class (H7);
- the certified sandboxes are reused, never relaxed: P3B1 (``BoxCopyBase``: no delete, move,
  rename or overwrite primitive is reachable), P3A (``FilingBase``) and P3B2 (``ArchiveBase``,
  which opens the service gate inside the sandbox only, as P3B2 itself does);
- multi-process tests start real independent Python processes (``subprocess``) that install
  the same fail-closed guard before importing anything from the CRM.

``EXECUTION_ENABLED`` stays False in the code; ``ScopeTests`` prove it. Nothing here applies a
migration to the habitual database or reaches Box.
"""
import ast
import gc
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlparse
from urllib.request import url2pathname

from backend.services import document_inbox_service as inbox
from backend.services import document_viewer_archive_permission_service as permission
from backend.services import document_viewer_archive_repository as repo
from backend.services import document_viewer_box_archive_service as archive
from backend.services import document_viewer_filing_plan_service as filing
from backend.services import document_viewer_link_service as link_service
from backend.services import expedient_service
from database import connection
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_box_from_viewer as p3b2
from scripts.tests import test_document_viewer_dv25_box_hardening as p3b1
from scripts.tests import test_document_viewer_dv25_filing_plan as p3a


REPO_ROOT = dv24.REPO_ROOT
HABITUAL_DB = Path(connection.__file__).resolve().with_name("quesada.db")
PERMISSION = REPO_ROOT / "backend" / "services" / "document_viewer_archive_permission_service.py"
REPOSITORY = REPO_ROOT / "backend" / "services" / "document_viewer_archive_repository.py"
FRONTEND = REPO_ROOT / "frontend"
# The real readers, captured before DV24's fixtures replace them with fakes.
REAL_CLIENT_OPTIONS = inbox.client_autocomplete_options
REAL_EXPEDIENT_OPTIONS = inbox.expedient_autocomplete_options_for_client
KEY = "EXPEDIENTE:100:SOLICITANTE"  # P3B1 synthetic catalog: PASAPORTE · SOLICITANTE
NAME = "PASAPORTE SOLICITANTE.pdf"
DESTRUCTIVE = {"unlink", "remove", "rename", "replace", "rmtree", "rmdir", "removedirs", "move", "copy2",
               "copyfile", "copytree", "mkdir", "makedirs", "write_bytes", "write_text", "touch", "symlink"}


def db_target(database, uri=False):
    """Database file a ``sqlite3.connect`` call would open, or None for memory."""
    text = os.fsdecode(database) if isinstance(database, bytes) else os.fspath(database)
    if text in ("", ":memory:"):
        return None
    if uri or text.startswith("file:"):
        parsed = urlparse(text)
        if "mode=memory" in parsed.query:
            return None
        return Path(url2pathname(parsed.path))
    return Path(text)


def habitual_fingerprint():
    """(name, size, mtime_ns, SHA-256) of the habitual database and its side files."""
    state = []
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = HABITUAL_DB.with_name(HABITUAL_DB.name + suffix)
        if path.exists():
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            st = path.stat()
            state.append((path.name, st.st_size, st.st_mtime_ns, digest.hexdigest()))
    return state


def sandbox_tree(root, skip=("previews",)):
    """(relative path, kind, SHA-256) of everything under ``root``; links are not followed."""
    entries, pending = [], [Path(root)]
    while pending:
        folder = pending.pop()
        for child in sorted(folder.iterdir()):
            relative = child.relative_to(root).as_posix()
            if relative.split("/")[0] in skip or child.name.endswith(("-journal", "-wal", "-shm")):
                continue
            if filing._redirects(child):
                entries.append((relative, "link", None))
            elif child.is_dir():
                entries.append((relative, "dir", None))
                pending.append(child)
            else:
                entries.append((relative, "file", hashlib.sha256(child.read_bytes()).hexdigest()))
    return sorted(entries)


def database_state(db):
    """Full schema and every row of every table."""
    with closing(sqlite3.connect(db)) as conn:
        schema = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        rows = {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
    return schema, rows


def make_dir_link(test, target, link):
    """Directory symlink if allowed, otherwise an NTFS junction (no privilege needed)."""
    try:
        os.symlink(target, link, target_is_directory=True)
        test.addCleanup(os.unlink if os.name != "nt" else os.rmdir, link)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        test.addCleanup(os.rmdir, link)


HABITUAL_BEFORE = []


def setUpModule():
    HABITUAL_BEFORE[:] = habitual_fingerprint()


def tearDownModule():
    if habitual_fingerprint() != HABITUAL_BEFORE:
        raise AssertionError("The habitual database changed during the security suite.")


class SandboxMixin:
    """Fail-closed isolation of every SQLite connection (H7)."""

    def sandbox(self, root, db):
        self.sandbox_root = Path(root).resolve()
        self.sqlite_violations = []
        self.addCleanup(lambda: self.assertEqual(self.sqlite_violations, []))
        real_connect = sqlite3.connect

        def guarded(database, *args, **kwargs):
            target = db_target(database, kwargs.get("uri", False))
            if target is not None:
                resolved = target.resolve()
                if resolved != self.sandbox_root and self.sandbox_root not in resolved.parents:
                    self.sqlite_violations.append(str(resolved))
                    raise AssertionError(f"SQLite connection outside the sandbox: {resolved}")
            return real_connect(database, *args, **kwargs)

        for owner, name, value in ((sqlite3, "connect", guarded), (connection, "DB_PATH", str(db)),
                                   (expedient_service, "DB_PATH", Path(db))):
            patcher = patch.object(owner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class SandboxCase(SandboxMixin, unittest.TestCase):
    """Light sandbox: a temporary CRM database, the Bandeja root inside it and the guard."""

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(gc.collect)  # unclosed ``with get_connection()`` handles lock files on Windows
        self.root = Path(temp.name).resolve()
        self.db = self.root / "crm.db"
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(dv24.CRM_SQL)
        self.sandbox(self.root, self.db)
        for name, sub in (("INBOX_ROOT", ""), ("INBOX_ORIGINALS", "originals"), ("INBOX_PROCESSED", "processed"),
                          ("INBOX_REJECTED", "rejected"), ("INBOX_TMP", "tmp")):
            patcher = patch.object(inbox, name, self.root / "bandeja" / sub if sub else self.root / "bandeja")
            patcher.start()
            self.addCleanup(patcher.stop)

    def execute(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute(sql, params)
            conn.commit()


# ---------------------------------------------------------------------- H7


class IsolationTests(SandboxCase):
    def test_connections_outside_the_sandbox_fail_closed(self):
        for database, uri in ((str(HABITUAL_DB), False), (HABITUAL_DB.as_uri() + "?mode=ro", True),
                              (HABITUAL_DB, False), (str(REPO_ROOT / "otra.db"), False)):
            with self.subTest(database=database), self.assertRaises(AssertionError):
                sqlite3.connect(database, uri=uri)
        self.assertEqual(len(self.sqlite_violations), 4)
        self.sqlite_violations.clear()
        self.assertFalse((REPO_ROOT / "otra.db").exists())
        # Every module-level default points to the sandbox, and the helpers obey it.
        self.assertEqual(Path(connection.DB_PATH), self.db)
        self.assertEqual(Path(expedient_service.DB_PATH), self.db)
        with closing(connection.get_readonly_connection()) as conn:
            self.assertEqual(conn.execute("SELECT username FROM users WHERE id = 1").fetchone()[0], "ana")
        with closing(sqlite3.connect(":memory:")) as conn:
            self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)

    def test_uri_and_bytes_targets_are_resolved(self):
        self.assertEqual(db_target(self.db.as_uri() + "?mode=rw", True).resolve(), self.db)
        self.assertEqual(db_target(os.fsencode(self.db)).resolve(), self.db)
        self.assertIsNone(db_target("file:memdb?mode=memory&cache=shared", True))


# ---------------------------------------------------------------------- H1


class Contract:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def grants(self, user, *, db_path=None):
        self.calls.append(user["id"])
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer(user) if callable(self.answer) else self.answer


class PermissionTests(SandboxCase):
    def test_without_an_approved_contract_everyone_is_denied(self):
        cases = [
            (None, permission.NO_ACTOR), ({}, permission.NO_ACTOR), ("ana", permission.NO_ACTOR),
            ({"id": 99}, permission.NOT_AUTHENTICATED),                       # unknown user
            ({"id": 3, "username": "baja"}, permission.NOT_AUTHENTICATED),    # deactivated
            ({"id": 1, "username": "luis"}, permission.NOT_AUTHENTICATED),    # forged username
            ({"id": "1 OR 1=1"}, permission.NOT_AUTHENTICATED),
            ({"id": 1, "username": "ana"}, permission.CONTRACT_MISSING),      # active is not enough
            ({"id": 1, "username": "ana", "role": "admin", "is_admin": True,
              "permissions": ["archive_box"]}, permission.CONTRACT_MISSING),  # client claims ignored
        ]
        for actor, reason in cases:
            with self.subTest(actor=actor):
                decision = permission.authorize_archive(actor, db_path=self.db)
                self.assertEqual((decision.outcome, decision.allowed, decision.reason),
                                 (permission.DENIED, False, reason))
        self.assertIsNone(permission.APPROVED_CONTRACT)
        # The real gate stays closed regardless.
        self.assertIs(archive.EXECUTION_ENABLED, False)
        self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)

    def test_only_an_installed_contract_allows_and_it_fails_closed(self):
        only_ana = Contract(lambda user: user["id"] == 1)
        with patch.object(permission, "APPROVED_CONTRACT", only_ana):
            allowed = permission.authorize_archive({"id": 1, "username": "ana"}, db_path=self.db)
            self.assertEqual((allowed.allowed, allowed.user), (True, {"id": 1, "username": "ana"}))
            luis = permission.authorize_archive({"id": 2, "username": "luis"}, db_path=self.db)
            self.assertEqual((luis.allowed, luis.reason), (False, permission.NOT_GRANTED))  # insufficient
            for actor in ({"id": 3}, {"id": 2, "username": "ana"}, {"id": 99}):
                with self.subTest(actor=actor):
                    self.assertEqual(permission.authorize_archive(actor, db_path=self.db).reason,
                                     permission.NOT_AUTHENTICATED)
            # The contract is never asked about an actor that is not authenticated.
            self.assertEqual(only_ana.calls, [1, 2])
            self.execute("UPDATE users SET is_active = 0 WHERE id = 1")
            self.assertFalse(permission.authorize_archive({"id": 1, "username": "ana"}, db_path=self.db).allowed)
        for answer, reason in (("yes", permission.NOT_GRANTED), (1, permission.NOT_GRANTED),
                               (None, permission.NOT_GRANTED), (RuntimeError("caído"), permission.CONTRACT_ERROR)):
            with self.subTest(answer=answer), patch.object(permission, "APPROVED_CONTRACT", Contract(answer)):
                decision = permission.authorize_archive({"id": 2, "username": "luis"}, db_path=self.db)
                self.assertEqual((decision.allowed, decision.reason), (False, reason))

    def test_unavailable_user_table_denies(self):
        self.execute("DROP TABLE users")
        decision = permission.authorize_archive({"id": 1, "username": "ana"}, db_path=self.db)
        self.assertEqual((decision.allowed, decision.reason), (False, permission.NOT_AUTHENTICATED))


# ---------------------------------------------------------------------- H2 (single process)


class Crash(BaseException):
    """Simulated process death: not an Exception, nothing in ``run_intent`` catches it."""


class IntentStoreTests(SandboxCase):
    def setUp(self):
        super().setUp()
        self.schema_before = database_state(self.db)[0]
        repo.apply_schema(self.db)
        self.store = repo.SqliteArchiveIntentStore(self.db)
        self.evidence_answer = ("", False)
        self.calls = []

    def intent(self, item=6, **changes):
        values = dict(inbox_item_id=item, client_id=7, expedient_id=42, subfolder="01 IDENTIDAD",
                      nomenclature_key=KEY, source_sha256="a" * 64, requested_by_user_id=1)
        values.update(changes)
        return repo.ArchiveIntent(**values)

    def operation(self, result=None, error=None):
        def run():
            self.calls.append(1)
            if error is not None:
                raise error
            return {"destination_path": "C:/box/EXP-42/" + NAME} if result is None else result
        return run

    def run_intent(self, intent, operation, now=None, store=None):
        return repo.run_intent(store or self.store, intent, operation,
                               evidence=lambda record: self.evidence_answer, now=now)

    @staticmethod
    def later():
        return datetime.now(timezone.utc) + repo.LEASE + timedelta(minutes=1)

    def rows(self):
        return database_state(self.db)[1]["document_viewer_archive_intents"]

    def test_migration_is_explicit_additive_and_never_on_the_habitual_database(self):
        schema = database_state(self.db)[0]
        added = sorted(name for _type, name, _sql in schema if (_type, name, _sql) not in self.schema_before)
        # SQLite backs the column-level UNIQUE on idempotency_key with an internal
        # index (sqlite_autoindex_<table>_1); it is part of the schema, not noise.
        self.assertEqual(added, ["document_viewer_archive_intents",
                                 "sqlite_autoindex_document_viewer_archive_intents_1",
                                 "uq_document_viewer_archive_intents_active_item"])
        with closing(sqlite3.connect(self.db)) as conn:
            unique = {name: bool(is_unique) for _seq, name, is_unique, *_rest
                      in conn.execute("PRAGMA index_list(document_viewer_archive_intents)")}
            autoindex_columns = [row[2] for row in conn.execute(
                "PRAGMA index_info(sqlite_autoindex_document_viewer_archive_intents_1)")]
        self.assertTrue(unique["sqlite_autoindex_document_viewer_archive_intents_1"])
        self.assertEqual(autoindex_columns, ["idempotency_key"])
        repo.apply_schema(self.db)  # idempotent
        self.assertEqual(database_state(self.db)[0], schema)
        for target in (None, HABITUAL_DB, str(HABITUAL_DB)):
            with self.subTest(target=target):
                with self.assertRaises(repo.ArchiveIntentError):
                    repo.apply_schema(target)
                with self.assertRaises(repo.ArchiveIntentError):
                    repo.SqliteArchiveIntentStore(target)
        # A database without the migration: the store neither creates nor migrates; nothing runs.
        bare = self.root / "sin_migrar.db"
        with closing(sqlite3.connect(bare)) as conn:
            conn.executescript(dv24.CRM_SQL)
        before = database_state(bare)
        outcome = self.run_intent(self.intent(), self.operation(), store=repo.SqliteArchiveIntentStore(bare))
        self.assertEqual(outcome.status, repo.UNAVAILABLE)
        self.assertEqual((self.calls, database_state(bare)), ([], before))
        missing = repo.SqliteArchiveIntentStore(self.root / "no_existe.db")
        self.assertEqual(self.run_intent(self.intent(), self.operation(), store=missing).status, repo.UNAVAILABLE)
        self.assertFalse((self.root / "no_existe.db").exists())

    def test_same_request_runs_once_and_returns_the_recorded_result(self):
        first = self.run_intent(self.intent(), self.operation())
        self.assertEqual((first.status, first.destination_path), (repo.DONE, "C:/box/EXP-42/" + NAME))
        self.assertEqual((first.record.state, first.record.fence), (repo.REGISTERED, 1))
        for again in (self.intent(), self.intent(requested_by_user_id=2)):  # the actor is not in the key
            outcome = self.run_intent(again, self.operation())
            self.assertEqual((outcome.status, outcome.destination_path), (repo.ALREADY_DONE, first.destination_path))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.rows()), 1)

    def test_a_request_for_an_item_in_flight_is_refused_on_any_key(self):
        with self.assertRaises(Crash):
            self.run_intent(self.intent(), self.operation(error=Crash()))
        self.assertEqual(self.store.get(self.intent().key).state, repo.CLAIMED)
        for name, other in (("same request", self.intent()), ("other folder", self.intent(subfolder="")),
                            ("other content", self.intent(source_sha256="b" * 64))):
            with self.subTest(name):
                outcome = self.run_intent(other, self.operation())
                self.assertEqual(outcome.status, repo.IN_PROGRESS)
                self.assertEqual(outcome.record.key, self.intent().key)
        self.assertEqual(self.run_intent(self.intent(item=7), self.operation()).status, repo.DONE)
        self.assertEqual(len(self.calls), 2)

    def test_stale_claim_is_reconciled_conservatively_never_retried(self):
        with self.assertRaises(Crash):
            self.run_intent(self.intent(), self.operation(error=Crash()))
        # No registered copy in Bandeja: human review, nothing is copied again.
        outcome = self.run_intent(self.intent(), self.operation(), now=self.later)
        self.assertEqual((outcome.status, outcome.record.state, outcome.record.fence),
                         (repo.REVIEW_REQUIRED, repo.NEEDS_REVIEW, 2))
        for request in (self.intent(), self.intent(subfolder="")):
            self.assertIn(self.run_intent(request, self.operation(), now=self.later).status,
                          (repo.REVIEW_REQUIRED, repo.IN_PROGRESS))
        # Registered and intact in Bandeja: the request is reconciled as done.
        with self.assertRaises(Crash):
            self.run_intent(self.intent(item=8), self.operation(error=Crash()))
        self.evidence_answer = ("C:/box/EXP-42/" + NAME, True)
        outcome = self.run_intent(self.intent(item=8), self.operation(), now=self.later)
        self.assertEqual((outcome.status, outcome.record.state, outcome.destination_path),
                         (repo.RECOVERED, repo.REGISTERED, "C:/box/EXP-42/" + NAME))
        self.assertEqual(self.run_intent(self.intent(item=8), self.operation()).status, repo.ALREADY_DONE)
        # Evidence that is not exactly True (or fails) is not enough.
        for answer in (("C:/x.pdf", 1), ("C:/x.pdf", False)):
            item = 20 + len(self.calls)
            with self.assertRaises(Crash):
                self.run_intent(self.intent(item=item), self.operation(error=Crash()))
            self.evidence_answer = answer
            self.assertEqual(self.run_intent(self.intent(item=item), self.operation(), now=self.later).status,
                             repo.REVIEW_REQUIRED)
        self.assertEqual(len(self.calls), 4)  # only the crashed attempts ran

    def test_rejection_without_writes_can_be_retried_with_a_new_fence(self):
        refused = self.run_intent(self.intent(), self.operation(error=repo.IntentRejected("Rechazo simulado.")))
        self.assertEqual((refused.status, refused.message), (repo.REFUSED, "Rechazo simulado."))
        self.assertEqual(self.store.get(self.intent().key).state, repo.REJECTED)
        retried = self.run_intent(self.intent(), self.operation())
        self.assertEqual((retried.status, retried.record.fence), (repo.DONE, 2))

    def test_possible_writes_and_unknown_failures_go_to_review_once(self):
        incomplete = self.run_intent(self.intent(), self.operation(
            error=repo.IntentIncomplete("Copia sin registrar.", "C:/box/EXP-42/" + NAME)))
        self.assertEqual((incomplete.status, incomplete.written_path),
                         (repo.REVIEW_REQUIRED, "C:/box/EXP-42/" + NAME))
        unknown = self.run_intent(self.intent(item=7), self.operation(error=OSError("disco")))
        self.assertEqual(unknown.status, repo.REVIEW_REQUIRED)
        for item in (6, 7):
            self.assertEqual(self.store.get(self.intent(item=item).key).state, repo.NEEDS_REVIEW)
            self.assertEqual(self.run_intent(self.intent(item=item), self.operation()).status, repo.REVIEW_REQUIRED)
        self.assertEqual(len(self.calls), 2)

    def test_a_late_owner_is_fenced_out(self):
        intent, inner = self.intent(), []

        def slow_owner():
            self.calls.append(1)
            # While this owner works, another process finds the claim expired and reconciles it.
            inner.append(self.run_intent(intent, self.operation(), now=self.later))
            return {"destination_path": "C:/box/EXP-42/" + NAME}

        outcome = self.run_intent(intent, slow_owner)
        self.assertEqual(inner[0].status, repo.REVIEW_REQUIRED)
        self.assertEqual(outcome.status, repo.FENCED)
        record = self.store.get(intent.key)
        self.assertEqual((record.state, record.fence), (repo.NEEDS_REVIEW, 2))
        self.assertEqual(len(self.calls), 1)

    def test_threads_with_their_own_connections_claim_once(self):
        barrier, results = threading.Barrier(8), []

        def slow():
            self.calls.append(1)
            time.sleep(0.3)
            return {"destination_path": "C:/box/EXP-42/" + NAME}

        def worker():
            barrier.wait(10)
            results.append(self.run_intent(self.intent(), slow).status)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(results.count(repo.DONE), 1)
        self.assertLessEqual(set(results), {repo.DONE, repo.IN_PROGRESS, repo.ALREADY_DONE})
        self.assertEqual((len(results), len(self.calls)), (8, 1))

    def test_requests_are_validated(self):
        for changes in ({"source_sha256": "A" * 64}, {"source_sha256": "x"}, {"inbox_item_id": 0},
                        {"client_id": True}, {"expedient_id": "42"}, {"requested_by_user_id": -1},
                        {"subfolder": None}, {"nomenclature_key": 3}):
            with self.subTest(changes=changes), self.assertRaises(repo.ArchiveIntentError):
                self.intent(**changes)
        self.assertNotEqual(self.intent().key, self.intent(subfolder="").key)
        self.assertRegex(self.intent().key, r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------- H2 (independent processes)


CHILD = r"""
import json, os, sqlite3, sys, time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

cfg = json.loads(sys.argv[1])
root = Path(cfg["root"]).resolve()
real_connect = sqlite3.connect


def guarded(database, *args, **kwargs):
    text = os.fsdecode(database) if isinstance(database, bytes) else os.fspath(database)
    if text not in ("", ":memory:"):
        if kwargs.get("uri") or text.startswith("file:"):
            text = url2pathname(urlparse(text).path)
        target = Path(text).resolve()
        if target != root and root not in target.parents:
            sys.stderr.write("SANDBOX VIOLATION %s\n" % target)
            sys.stderr.flush()
            os._exit(90)
    return real_connect(database, *args, **kwargs)


sqlite3.connect = guarded

from database import connection
connection.DB_PATH = cfg["db"]
from backend.services import expedient_service
expedient_service.DB_PATH = Path(cfg["db"])
from backend.services import document_inbox_service as inbox
bandeja = Path(cfg["bandeja"])
inbox.INBOX_ROOT = bandeja
inbox.INBOX_ORIGINALS = bandeja / "originals"
inbox.INBOX_PROCESSED = bandeja / "processed"
inbox.INBOX_REJECTED = bandeja / "rejected"
inbox.INBOX_TMP = bandeja / "tmp"
from backend.services import document_viewer_archive_repository as repo

crash = cfg.get("crash")
real_register = inbox._register_box_copy


def register(*args):
    if crash == "before_register":
        os._exit(18)
    real_register(*args)
    if crash == "after_register":
        os._exit(17)


inbox._register_box_copy = register
real_copy = inbox.copy_inbox_item_to_expedient_box


def copy(*args, **kwargs):
    time.sleep(cfg.get("hold", 0))
    return real_copy(*args, **kwargs)


intent = repo.ArchiveIntent(**cfg["intent"])
Path(cfg["ready"]).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 120
while not Path(cfg["go"]).exists():
    if time.monotonic() > deadline:
        os._exit(91)
    time.sleep(0.01)
outcome = repo.run_intent(repo.SqliteArchiveIntentStore(cfg["db"]), intent,
                          repo.governed_box_copy(intent, copy=copy),
                          evidence=repo.registered_copy_evidence(cfg["db"]))
print(json.dumps({"status": outcome.status, "destination": outcome.destination_path}))
"""


class MultiProcessTests(SandboxMixin, p3b1.BoxCopyBase):
    """Real processes; the certified P3B1 copy runs FOR REAL inside each of them."""

    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)
        repo.apply_schema(self.db)
        self.item = self.add_item()
        self.intent = repo.ArchiveIntent(
            inbox_item_id=self.item, client_id=7, expedient_id=42, subfolder="", nomenclature_key=KEY,
            source_sha256=p3b1.sha(self.sources[self.item][1]), requested_by_user_id=1)
        self.go = self.root / "go"

    def spawn(self, name, db, **extra):
        config = {"root": str(self.root), "db": str(db), "bandeja": str(self.root / "bandeja"),
                  "intent": asdict(self.intent), "ready": str(self.root / f"{name}.ready"),
                  "go": str(self.go), **extra}
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), env.get("PYTHONPATH", "")]))
        process = subprocess.Popen([sys.executable, "-c", CHILD, json.dumps(config)], cwd=REPO_ROOT, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def start(self, *processes):
        deadline = time.monotonic() + 180
        names = [f"{index}.ready" for index in range(len(processes))]
        while not all((self.root / name).exists() for name in names):
            self.assertTrue(all(process.poll() is None for process in processes), "child died before start")
            self.assertLess(time.monotonic(), deadline, "children did not start")
            time.sleep(0.05)
        self.go.write_text("go", encoding="utf-8")
        finished = []
        for process in processes:
            out, err = process.communicate(timeout=180)
            lines = [line for line in out.splitlines() if line.strip()]
            finished.append((process.returncode, json.loads(lines[-1]) if process.returncode == 0 else err))
        return finished

    def files(self):
        return sorted(path.name for path in self.box.glob("PASAPORTE SOLICITANTE*"))

    def intents(self, db=None):
        with closing(sqlite3.connect(db or self.db)) as conn:
            return conn.execute("SELECT state, destination_path FROM document_viewer_archive_intents").fetchall()

    def later(self):
        return datetime.now(timezone.utc) + repo.LEASE + timedelta(minutes=1)

    def forbidden_copy(self, *args, **kwargs):
        raise AssertionError("a recovery must never copy again")

    def test_two_processes_on_one_shared_database_copy_and_register_once(self):
        results = self.start(self.spawn("0", self.db, hold=1.5), self.spawn("1", self.db, hold=1.5))
        self.assertEqual([code for code, _ in results], [0, 0], results)
        statuses = sorted(answer["status"] for _code, answer in results)
        self.assertIn(statuses, ([repo.DONE, repo.IN_PROGRESS], [repo.ALREADY_DONE, repo.DONE]))
        self.assertEqual(self.files(), [NAME])  # never a _2 of the same document
        self.assertEqual((self.box / NAME).read_bytes(), self.sources[self.item][1])
        self.assertEqual(len(self.events(self.item, "copied_to_box")), 1)
        self.assertEqual(self.item_state(self.item)["copied_to_box_path"], str(self.box / NAME))
        self.assertEqual(self.intents(), [(repo.REGISTERED, str(self.box / NAME))])

    def test_independent_databases_are_not_coordination_between_machines(self):
        """Two local databases (one per PC): each one claims, nothing is coordinated."""
        copies = []
        for name in ("pc_a.db", "pc_b.db"):
            target = self.root / name
            with closing(sqlite3.connect(self.db)) as source, closing(sqlite3.connect(target)) as dest:
                source.backup(dest)
            copies.append(target)
        results = self.start(self.spawn("0", copies[0], hold=0.5), self.spawn("1", copies[1], hold=0.5))
        self.assertEqual([code for code, _ in results], [0, 0], results)
        # Both "win": the claim only covers processes that share ONE transactional authority.
        self.assertEqual([answer["status"] for _code, answer in results], [repo.DONE, repo.DONE])
        for target in copies:
            self.assertEqual([state for state, _ in self.intents(target)], [repo.REGISTERED])
        # Depending on timing the second machine reuses the first file or leaves a _2: no guarantee.
        self.assertIn(len(self.files()), (1, 2))
        self.assertIs(repo.MULTI_HOST_GUARANTEE, False)
        self.assertIs(repo.SqliteArchiveIntentStore(self.db).multi_host_guarantee, False)

    def test_crash_after_register_is_recovered_without_another_file(self):
        [(code, _err)] = self.start(self.spawn("0", self.db, crash="after_register"))
        self.assertEqual(code, 17)
        self.assertEqual(self.intents(), [(repo.CLAIMED, None)])
        self.assertEqual(self.item_state(self.item)["status"], "copied_to_box")
        store = repo.SqliteArchiveIntentStore(self.db)
        operation = repo.governed_box_copy(self.intent, copy=self.forbidden_copy)
        evidence = repo.registered_copy_evidence(self.db)
        early = repo.run_intent(store, self.intent, operation, evidence=evidence)
        self.assertEqual(early.status, repo.IN_PROGRESS)  # the lease has not expired yet
        recovered = repo.run_intent(store, self.intent, operation, evidence=evidence, now=self.later)
        self.assertEqual((recovered.status, recovered.destination_path), (repo.RECOVERED, str(self.box / NAME)))
        self.assertEqual(repo.run_intent(store, self.intent, operation, evidence=evidence).status,
                         repo.ALREADY_DONE)
        self.assertEqual(self.files(), [NAME])
        self.assertEqual(len(self.events(self.item, "copied_to_box")), 1)

    def test_crash_between_verify_and_register_goes_to_review_and_keeps_the_file(self):
        [(code, _err)] = self.start(self.spawn("0", self.db, crash="before_register"))
        self.assertEqual(code, 18)
        self.assertEqual(self.item_state(self.item)["status"], "linked")
        self.assertEqual(self.files(), [NAME])  # verified copy, not registered
        store = repo.SqliteArchiveIntentStore(self.db)
        operation = repo.governed_box_copy(self.intent, copy=self.forbidden_copy)
        evidence = repo.registered_copy_evidence(self.db)
        outcome = repo.run_intent(store, self.intent, operation, evidence=evidence, now=self.later)
        self.assertEqual(outcome.status, repo.REVIEW_REQUIRED)
        self.assertEqual(repo.run_intent(store, self.intent, operation, evidence=evidence, now=self.later).status,
                         repo.REVIEW_REQUIRED)
        self.assertEqual(self.intents(), [(repo.NEEDS_REVIEW, None)])
        # Nothing deleted, nothing duplicated, nothing registered behind the human's back.
        self.assertEqual(self.files(), [NAME])
        self.assertEqual((self.box / NAME).read_bytes(), self.sources[self.item][1])
        self.assertEqual(self.item_state(self.item)["status"], "linked")


# ---------------------------------------------------------------------- H3, H4, H5 (P3B1 backend)


class DestinationSafetyTests(SandboxMixin, p3b1.BoxCopyBase):
    """Windows scenarios through the certified copy, by nomenclature (the viewer's path)."""

    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)

    def event_messages(self, item_id):
        return [row["message"] for row in self.query(
            "SELECT message FROM document_inbox_events WHERE item_id = ? AND event_type = 'copied_to_box' "
            "ORDER BY id", (item_id,))]

    def failing_register(self):
        real = inbox._record_event

        def record(conn, item_id, kind, message="", metadata=None):
            if kind == "copied_to_box":
                raise sqlite3.OperationalError("database is locked (simulado)")
            return real(conn, item_id, kind, message, metadata)
        return patch.object(inbox, "_record_event", record)

    def test_missing_folder_is_never_created_for_a_viewer_copy(self):
        item = self.add_item()
        error = self.assert_refused(item, error=inbox.BoxCopyStaleDestination, subfolder="03 NUEVA/Sub",
                                    nomenclature_key=KEY)
        self.assertEqual(error.code, "STALE_DESTINATION")
        self.assertIsInstance(error, inbox.BoxCopyRejected)
        self.assertFalse((self.box / "03 NUEVA").exists())

    def test_folder_deleted_after_the_review_is_stale_and_not_recreated(self):
        item = self.add_item()
        folder = self.box / "02 LABORAL" / "Contratos"
        self.assertEqual(filing.check_subfolder("02 LABORAL/Contratos"), "02 LABORAL/Contratos")
        self.real["rmdir"](folder)  # removed in Box between the review and the copy
        self.assert_refused(item, error=inbox.BoxCopyStaleDestination, subfolder="02 LABORAL/Contratos",
                            nomenclature_key=KEY)
        self.assertFalse(folder.exists())

    def test_hostile_destinations_are_refused_without_any_write(self):
        self.make_dir_link(self.outside, self.box / "salida")  # P3B1's helper: behind its guard
        self.protect_box()
        item = self.add_item()
        for subfolder in ("salida", "salida/secreta", "..", "../fuera", "01 IDENTIDAD/../../fuera",
                          "\\\\servidor\\box", "//servidor/box", "\\\\?\\C:\\fuera", str(self.outside),
                          "C:/fuera", "C:fuera", "CON", "01 IDENTIDAD/NUL", "carpeta.", "a:b"):
            with self.subTest(subfolder=subfolder):
                self.assert_refused(item, subfolder=subfolder, nomenclature_key=KEY)
        self.assertEqual(self.item_state(item)["status"], "linked")

    def test_collision_changed_original_and_identical_previous_file(self):
        self.seed(self.box / NAME, b"otro documento previo")
        self.protect_box()
        item = self.add_item()
        result = self.copy(item, nomenclature_key=KEY)
        self.assert_registered(item, result, self.box / "PASAPORTE SOLICITANTE_2.pdf")
        trace = result["box_copy"]
        self.assertEqual((trace["collision_decision"], trace["provenance"], trace["created_by_this_operation"]),
                         ("renamed", "created", True))
        self.assertEqual(self.event_messages(item), ["Documento copiado a carpeta Box del expediente"])
        self.assert_refused(self.add_item(sha256="f" * 64), nomenclature_key=KEY)  # original changed
        # An identical file that was already in Box is reused, never overwritten nor attributed.
        twin = self.add_item(content=b"%PDF gemelo previo")
        self.seed(self.box / "PASAPORTE SOLICITANTE_3.pdf", b"%PDF gemelo previo")
        self.protect_box()
        result = self.copy(twin, nomenclature_key=KEY)
        self.assert_registered(twin, result, self.box / "PASAPORTE SOLICITANTE_3.pdf")
        trace = result["box_copy"]
        self.assertEqual((trace["collision_decision"], trace["provenance"], trace["created_by_this_operation"]),
                         ("reused_identical", "preexisting_unverified", False))
        [message] = self.event_messages(twin)
        self.assertIn("no lo creó esta operación", message)
        [event] = self.events(twin, "copied_to_box")
        self.assertEqual(event["metadata"]["provenance"], "preexisting_unverified")

    def test_register_failure_then_retry_is_attributed_only_to_its_own_copy(self):
        item = self.add_item()
        with self.failing_register(), self.assertRaises(inbox.BoxCopyIncomplete):
            self.copy(item, nomenclature_key=KEY)
        result = self.copy(item, nomenclature_key=KEY)
        self.assert_registered(item, result, self.box / NAME)
        self.assertEqual((result["box_copy"]["collision_decision"], result["box_copy"]["provenance"]),
                         ("reused_identical", "own_unregistered_copy"))
        self.assertEqual(self.files_named("PASAPORTE SOLICITANTE"), [NAME])
        # A previous identical file whose registration failed is not laundered into "own".
        other = self.add_item(content=b"%PDF previo identico", name="Otro.pdf")
        self.seed(self.box / "Otro.pdf", b"%PDF previo identico")
        self.protect_box()
        with self.failing_register(), self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(other)
        self.assertFalse(caught.exception.created)
        result = self.copy(other)
        self.assertEqual(result["box_copy"]["provenance"], "preexisting_unverified")

    def files_named(self, stem):
        return sorted(path.name for path in self.box.glob(f"{stem}*"))

    def test_toctou_swap_after_validation_is_detected_but_not_prevented(self):
        """H3 residual: Python cannot create a file relative to a held directory handle on Windows."""
        escape = self.root / "fuera_toctou"
        escape.mkdir()
        folder = self.box / "02 LABORAL" / "Contratos"
        real_folder = inbox._box_destination_folder

        def validated_then_swapped(root, relative, create_missing=True):
            result = real_folder(root, relative, create_missing)
            self.real["rmdir"](folder)
            self.make_dir_link(escape, folder)
            return result

        item = self.add_item()
        with patch.object(inbox, "_box_destination_folder", validated_then_swapped), \
                self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item, subfolder="02 LABORAL/Contratos", nomenclature_key=KEY)
        self.assertEqual(caught.exception.stage, "verify")
        state = self.item_state(item)
        self.assertEqual((state["status"], state["copied_to_box_path"]), ("linked", None))
        self.assertEqual(self.events(item, "copied_to_box"), [])
        # The write escaped through the swapped link: detected, never registered, never deleted.
        self.assertEqual(sorted(path.name for path in escape.iterdir()), [NAME])


# ---------------------------------------------------------------------- H8 (P3A preview = P3B1 copy)


class ConvergenceTests(SandboxMixin, p3a.FilingBase):
    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)

    def test_every_offered_folder_is_accepted_by_the_copy_without_creating_anything(self):
        context = self.context()
        offered = [folder.relative for folder in context.folders]
        self.assertEqual(offered, ["", "01 IDENTIDAD", "02 LABORAL", "02 LABORAL/Contratos"])
        with self.guard():
            for relative in offered:
                with self.subTest(relative=relative):
                    self.assertEqual(filing.check_subfolder(relative), relative)
                    self.assertEqual(filing.verify_folder(context, relative), relative)
                    folder, created = inbox._box_destination_folder(context.root.path, relative,
                                                                    create_missing=False)
                    self.assertEqual(created, [])
                    self.assertFalse(filing._redirects(folder))

    def test_names_the_copy_would_refuse_are_never_offered(self):
        def listing(path, relative_base=None):
            names = ("CON", "carpeta.", "aux.txt", "01 IDENTIDAD") if Path(path) == Path(relative_base) else ()
            return {"folders": [{"name": name} for name in names]}

        with patch.object(filing, "list_expediente_box_directory", listing):
            context = self.context()
        self.assertEqual([folder.relative for folder in context.folders], ["", "01 IDENTIDAD"])
        forged = replace(context, folders=(*context.folders, *(filing.FolderOption(name, name)
                                                               for name in ("CON", "carpeta.", "aux.txt"))))
        for relative in ("CON", "carpeta.", "aux.txt", "01 IDENTIDAD/../02 LABORAL"):
            with self.subTest(relative=relative):
                self.assertIsNone(filing.verify_folder(forged, relative))

    def test_root_that_is_a_link_junction_or_network_path_is_not_offered(self):
        link = self.root / "raiz_enlace"
        make_dir_link(self, self.box, link)
        for raw in (str(link), "\\\\servidor\\box\\EXP-42", "//servidor/box/EXP-42", "\\\\?\\C:\\box"):
            with self.subTest(raw=raw):
                self.set_box(42, raw)
                root = filing.expedient_root(42)
                self.assertEqual((root.available, root.message), (False, filing.NO_BOX))
        self.set_box(42, str(self.box))
        self.assertTrue(filing.expedient_root(42).available)

    def test_a_link_inside_the_root_pointing_inside_is_not_offered_either(self):
        make_dir_link(self, self.box / "01 IDENTIDAD", self.box / "alias")
        self.archive_before = self.tree()
        context = self.context()
        self.assertNotIn("alias", [folder.relative for folder in context.folders])
        self.assertIsNone(filing.verify_folder(replace(context, folders=(
            *context.folders, filing.FolderOption("alias", "alias"))), "alias"))


# ---------------------------------------------------------------------- H4, H5, H6 (viewer)


class ViewerSafetyTests(SandboxMixin, p3b2.ArchiveBase):
    """P3B2 sandbox (gate opened only here, as P3B2 does) plus the fail-closed guard."""

    def setUp(self):
        super().setUp()
        self.sandbox(self.root, self.db)

    def full_state(self):
        return database_state(self.db), sandbox_tree(self.root)

    def test_reviewed_folder_removed_before_the_copy_is_not_recreated(self):
        contratos = self.box / "02 LABORAL" / "Contratos"
        plan = self.prepare([6], folder="02 LABORAL/Contratos", choices={"inbox:6": p3b2.K[0]})
        self.assertEqual(len(plan.ready), 1)

        def removed_then_copied(item_id, **kwargs):
            contratos.rmdir()  # after the service's last check, before the certified copy
            return p3b2.REAL_COPY(item_id, **kwargs)

        self.copy.side_effect = removed_then_copied
        result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(6, archive.REJECTED)])
        self.assertIn("ya no existe", result.items[0].message)
        self.assertFalse(contratos.exists())
        row = self.row(6)
        self.assertEqual((row["status"], row["copied_to_box_path"]), ("linked", None))
        self.assertEqual(self.events(6), [])
        contratos.mkdir()  # the Box tree of FilingBase's tearDown

    def test_identical_file_already_in_box_is_not_attributed_to_this_copy(self):
        same = self.box / NAME
        same.write_bytes(self.source(6))
        self.archive_before = self.tree()
        plan = self.prepare([6], folder="", choices={"inbox:6": p3b2.K[0]})
        with self.guard():
            result = self.run_plan(plan)
        outcome, = result.items
        self.assertEqual((outcome.status, outcome.collision), (archive.ARCHIVED, "reused_identical"))
        self.assertIn("se registra sin duplicarlo", outcome.message)
        self.assertIn("No lo creó esta operación", outcome.message)
        event, = self.events(6)
        metadata = json.loads(event["metadata_json"])
        self.assertEqual((metadata["provenance"], metadata["created_by_this_operation"]),
                         ("preexisting_unverified", False))
        self.assertNotEqual(event["message"], "Documento copiado a carpeta Box del expediente")
        self.assertEqual(self.tree(), self.archive_before)

    def test_opening_navigating_and_cancelling_dialogs_change_no_schema_data_or_folder(self):
        # The real Bandeja readers, not DV24's fakes, behind the link dialog.
        self.patch(inbox, "client_autocomplete_options", REAL_CLIENT_OPTIONS)
        self.patch(inbox, "expedient_autocomplete_options_for_client", REAL_EXPEDIENT_OPTIONS)
        dialog = self.open_inbox([6, 1, 2])
        before = self.full_state()
        ensure = self.patch(inbox, "ensure_document_inbox_schema", side_effect=AssertionError("DDL"))
        dirs_calls = inbox._ensure_dirs.call_count  # DV24 replaces it with a recording mock
        with self.guard():
            form = self.open_form(dialog)
            self.pick(form.expedient_select, 42)
            self.pick(form.expedient_select, 43)
            self.pick(form.client_select, 8)
            form.cancel_button.on_click(None)
            self.button(dialog, "Doc siguiente").on_click(None)
            form = self.open_form(dialog)
            form.close()
            archive_form = self.open_archive(dialog)
            archive_form.close()
            self.button(dialog, "Doc anterior").on_click(None)
            archive_form = self.open_archive(dialog)
            self.choose(archive_form.folder_select, "01 IDENTIDAD")
            archive_form.cancel_button.on_click(None)
            self.button(dialog, "Cerrar").on_click(None)
        ensure.assert_not_called()
        self.assertEqual(inbox._ensure_dirs.call_count, dirs_calls)
        self.copy.assert_not_called()
        self.assertEqual(self.full_state(), before)


class ReaderSideEffectTests(SandboxCase):
    """H6 on a CRM without Bandeja tables: reading never creates them nor any folder."""

    def setUp(self):
        super().setUp()
        for name in ("ensure_document_inbox_schema", "_ensure_dirs"):
            patcher = patch.object(inbox, name, side_effect=AssertionError(name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.actor = {"id": 1, "username": "ana"}

    def test_link_readers_never_migrate_or_create_folders(self):
        before = database_state(self.db), sandbox_tree(self.root)
        document = {"key": "inbox:6", "name": "x.pdf", "path": str(self.root / "x.pdf"), "inbox_item_id": 6}
        checks = link_service.inspect_documents(self.actor, [document], db_path=self.db)
        self.assertEqual([(check.outcome, check.message) for check in checks],
                         [(link_service.REJECTED, link_service.ITEM_MISSING)])
        self.assertEqual([option["id"] for option in link_service.client_options()], [8, 7])
        self.assertEqual(sorted(option["id"] for option in link_service.expedient_options(7)), [42, 43, 51])
        with self.assertRaises(ValueError):
            inbox.get_inbox_item(6)
        self.assertEqual((database_state(self.db), sandbox_tree(self.root)), before)
        self.assertFalse((self.root / "bandeja").exists())


# ---------------------------------------------------------------------- scope


class ScopeTests(unittest.TestCase):
    def test_real_gate_stays_closed_and_permission_is_not_granted_in_code(self):
        tree = ast.parse(p3b2.SERVICE.read_text(encoding="utf-8"))
        values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                  and any(getattr(target, "id", None) == "EXECUTION_ENABLED" for target in node.targets)]
        self.assertEqual(values, [False])
        tree = ast.parse(PERMISSION.read_text(encoding="utf-8"))
        values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                  and any(getattr(target, "id", None) == "APPROVED_CONTRACT" for target in node.targets)]
        self.assertEqual(values, [None])
        self.assertIs(repo.MULTI_HOST_GUARANTEE, False)

    def test_new_modules_have_no_destructive_primitive_and_no_sqlite_in_the_domain(self):
        for path in (PERMISSION, REPOSITORY):
            with self.subTest(path.name):
                modules = dv24.imported_modules(path)
                for forbidden in ("os", "shutil", "sqlite3", "subprocess", "flet", "frontend"):
                    self.assertFalse(any(m == forbidden or m.startswith(forbidden + ".") for m in modules),
                                     forbidden)
                self.assertEqual(p3a.called_names(path) & DESTRUCTIVE, set())
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "open":
                        self.assertEqual(node.args[0].value, "rb")
        # The physical copy is the certified P3B1 one: one call, no second implementation.
        tree = ast.parse(REPOSITORY.read_text(encoding="utf-8"))
        used = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                and getattr(node.value, "id", None) == "inbox"]
        self.assertEqual(used.count("copy_inbox_item_to_expedient_box"), 1)
        self.assertLessEqual(set(used), {"copy_inbox_item_to_expedient_box", "BoxCopyIncomplete"})

    def test_ui_never_migrates_nor_reaches_the_new_backend_directly(self):
        for path in sorted(FRONTEND.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for name in ("document_viewer_archive_repository", "apply_schema", "20261110_dv25_archive_claims"):
                self.assertNotIn(name, text, path)

    def test_readers_used_by_the_link_dialog_have_no_schema_side_effect(self):
        tree = ast.parse(Path(inbox.__file__).read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in ("get_inbox_item", "_query_inbox_items", "_annotate_single_inbox_duplicate",
                     "list_clients_for_inbox", "client_autocomplete_options", "list_expedients_for_client",
                     "expedient_autocomplete_options_for_client"):
            with self.subTest(name):
                calls = {getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                         for node in ast.walk(functions[name]) if isinstance(node, ast.Call)}
                self.assertEqual(calls & {"ensure_document_inbox_schema", "_ensure_dirs", "list_inbox_items",
                                          "mkdir", "executescript", "commit"}, set())


if __name__ == "__main__":
    unittest.main()
