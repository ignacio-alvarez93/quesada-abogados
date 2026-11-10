"""WO-DV24-P2: persistent per-document notes and contextual activity.

Synthetic PDFs and SQLite databases in a TemporaryDirectory only. The
operational database path is redirected to a file that must never appear;
Bandeja reads are fakes of the existing service functions and every
Bandeja/Box mutation is patched to fail the test if it is called.
"""
import ast
import copy
import importlib
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import fitz
import flet as ft

from backend.repositories import document_viewer_notes_repository as repository
from backend.services import document_inbox_service
from backend.services import document_viewer_notes_service as notes_service
from backend.services import document_viewer_service as viewer_service
from database import connection
from frontend.components import document_viewer_notes_panel as panel
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label, viewer_layout,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPEDIENTS = REPO_ROOT / "frontend" / "views" / "expedients_view.py"
INBOX = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"
MAIN = REPO_ROOT / "app" / "main.py"
FLET_SOURCES = (
    REPO_ROOT / "frontend" / "components" / "document_viewer_notes_panel.py",
    REPO_ROOT / "frontend" / "components" / "document_viewer_modal.py",
    REPO_ROOT / "frontend" / "components" / "document_viewer_multidoc.py",
)
DB_MODULES = ("sqlite3", "database")

USERS_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO users (id, username, password_hash, is_active)
VALUES (1, 'ana', 'x', 1), (2, 'luis', 'x', 1), (3, 'baja', 'x', 0);
"""
NOTE_COLUMNS = ["id", "document_kind", "document_ref", "inbox_item_id", "expediente_id",
                "relative_path", "content_sha256", "size_bytes", "body", "author_user_id",
                "author_username", "status", "request_id", "created_at"]
INBOX_MUTATIONS = ("ensure_document_inbox_schema", "link_inbox_item", "update_inbox_item_status",
                   "update_inbox_item_filename", "import_file_to_inbox",
                   "copy_inbox_item_to_expedient_box", "copy_document_inbox_batch_to_expedient_box",
                   "import_box_file_to_inbox", "bulk_import_box_files_to_inbox")


def make_pdf(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        document.new_page(width=150, height=150).insert_text((20, 30), text)
        document.save(path)


def walk(control):
    yield control
    for name in ("content", "title"):
        child = getattr(control, name, None)
        if isinstance(child, ft.Control):
            yield from walk(child)
    for child in getattr(control, "controls", None) or ():
        yield from walk(child)


def bind(path, names, scope):
    """Execute view closures at module level; free names resolve from scope."""
    found = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            found.setdefault(node.name, node)
    module = ast.Module(body=[found[name] for name in names], type_ignores=[])
    exec(compile(module, f"<{path.name}>", "exec"), scope)
    return scope


def imported_modules(path):
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def is_db_module(name):
    return any(name == db or name.startswith(db + ".") for db in DB_MODULES)


class NotesBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "crm.db"
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(USERS_SQL)
        # Anything reaching the operational database would create this file.
        self.operational = self.root / "operational.db"
        self.patch(connection, "DB_PATH", str(self.operational))
        self.actor = {"id": 1, "username": "ana"}

        # Expediente 42: three documents with the same name in different folders.
        self.exp_root = self.root / "box" / "EXP-42"
        self.exp_docs = [self.exp_root / folder / "Pasaporte.pdf" for folder in ("titular", "conyuge", "hijo")]
        self.exp_docs += [self.exp_root / "Contrato.pdf", self.exp_root / "Nomina.pdf"]
        for index, path in enumerate(self.exp_docs):
            make_pdf(path, f"expediente {index}")
        self.patch(viewer_service, "get_expediente_document_root", side_effect=self.expediente_root)

        # Bandeja: three items with the same visible name.
        self.inbox_docs = [self.root / "inbox" / f"{number}_Pasaporte.pdf" for number in (1, 2, 3)]
        for index, path in enumerate(self.inbox_docs):
            make_pdf(path, f"bandeja {index}")
        self.items = {index + 1: {
            "id": index + 1, "stored_path": str(path), "original_filename": "Pasaporte.pdf",
            "status": "pending", "client_id": 7, "expedient_id": None,
            "notes": "Descripción de bandeja" if index == 0 else "",
        } for index, path in enumerate(self.inbox_docs)}
        self.events = {1: [{"id": 5, "item_id": 1, "event_type": "imported",
                            "event_at": "2026-11-08 10:15:00", "message": "Documento importado",
                            "metadata_json": "{}"}]}
        self.items_before = copy.deepcopy(self.items)
        self.events_before = copy.deepcopy(self.events)
        self.patch(document_inbox_service, "get_inbox_item", side_effect=self.get_item)
        self.patch(document_inbox_service, "get_inbox_events",
                   side_effect=lambda item_id: copy.deepcopy(self.events.get(int(item_id), [])))
        for name in INBOX_MUTATIONS:
            self.patch(document_inbox_service, name, side_effect=AssertionError(name))
        self.snapshot()

    def tearDown(self):
        # Notes never touch documents, Bandeja items, their events or the operational DB.
        for path, (data, mtime) in self.files.items():
            self.assertEqual(path.read_bytes(), data, path)
            self.assertEqual(path.stat().st_mtime_ns, mtime, path)
        self.assertEqual(self.items, self.items_before)
        self.assertEqual(self.events, self.events_before)
        self.assertFalse(self.operational.exists())

    def patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def snapshot(self):
        self.files = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in self.exp_docs + self.inbox_docs}

    def expediente_root(self, expediente_id):
        if int(expediente_id) == 42:
            return {"expediente_id": 42, "root_path": str(self.exp_root.resolve()),
                    "exists": True, "message": ""}
        return {"expediente_id": int(expediente_id), "root_path": "", "exists": False,
                "message": "El expediente no tiene carpeta Box vinculada."}

    def get_item(self, item_id):
        item = self.items.get(int(item_id))
        if item is None:
            raise ValueError("No existe el documento de bandeja indicado.")
        return copy.deepcopy(item)

    def exp(self, index):
        return {"expediente_id": 42, "path": str(self.exp_docs[index])}

    def inbox(self, item_id):
        return {"inbox_item_id": item_id, "path": str(self.inbox_docs[item_id - 1])}

    def add(self, target, body, request_id=None, **kwargs):
        return notes_service.add_document_note(self.actor, target, body,
                                               request_id=request_id or uuid4().hex,
                                               db_path=self.db, **kwargs)

    def load(self, target):
        return notes_service.load_document_notes(self.actor, target, db_path=self.db)

    def bodies(self, target):
        return [note["body"] for note in self.load(target)["notes"]]

    def rows(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            try:
                return [dict(row) for row in conn.execute("SELECT * FROM document_viewer_notes ORDER BY id")]
            except sqlite3.OperationalError:
                return []  # schema not applied yet: nothing was written


class DocumentIdentityTests(NotesBase):
    def test_same_name_documents_keep_independent_notes(self):
        targets = [self.exp(0), self.exp(1), self.exp(2), self.inbox(1), self.inbox(2), self.inbox(3)]
        for index, target in enumerate(targets):
            self.add(target, f"nota {index}")
        for index, target in enumerate(targets):
            result = self.load(target)
            self.assertEqual([note["body"] for note in result["notes"]], [f"nota {index}"])
            self.assertEqual(result["identity"].name, "Pasaporte.pdf")
        rows = self.rows()
        self.assertEqual(len({row["document_ref"] for row in rows}), 6)
        self.assertEqual([row["relative_path"] for row in rows],
                         ["titular/Pasaporte.pdf", "conyuge/Pasaporte.pdf", "hijo/Pasaporte.pdf",
                          None, None, None])
        self.assertEqual([row["document_ref"] for row in rows[3:]], ["inbox:1", "inbox:2", "inbox:3"])
        self.assertEqual([row["inbox_item_id"] for row in rows], [None, None, None, 1, 2, 3])

    def test_paths_outside_scope_and_unregistered_files_are_rejected_without_writes(self):
        outside = self.root / "outside" / "Pasaporte.pdf"
        make_pdf(outside, "fuera")
        hidden = self.exp_root / ".oculto.pdf"
        make_pdf(hidden, "oculto")
        office_temp = self.exp_root / "~$borrador.docx"
        office_temp.write_bytes(b"temporal")
        binary = self.exp_root / "programa.exe"
        binary.write_bytes(b"MZ")
        cases = {
            "dotdot inside root": {"expediente_id": 42,
                                   "path": str(self.exp_root / "titular" / ".." / "conyuge" / "Pasaporte.pdf")},
            "relative escape": {"expediente_id": 42, "path": "../outside/Pasaporte.pdf"},
            "outside root": {"expediente_id": 42, "path": str(outside)},
            "hidden file": {"expediente_id": 42, "path": str(hidden)},
            "office temp file": {"expediente_id": 42, "path": str(office_temp)},
            "unsupported type": {"expediente_id": 42, "path": str(binary)},
            "missing file": {"expediente_id": 42, "path": str(self.exp_root / "falta.pdf")},
            "empty path": {"expediente_id": 42, "path": ""},
            "unknown expediente": {"expediente_id": 99, "path": str(self.exp_docs[0])},
            "invalid expediente": {"expediente_id": "abc", "path": str(self.exp_docs[0])},
            "no identity": {"path": str(self.exp_docs[0])},
            "inbox foreign file": {"inbox_item_id": 1, "path": str(self.inbox_docs[1])},
            "inbox unregistered pdf": {"inbox_item_id": 1, "path": str(outside)},
            "inbox missing item": {"inbox_item_id": 99, "path": str(self.inbox_docs[0])},
            "inbox relative path": {"inbox_item_id": 1, "path": self.inbox_docs[0].name},
        }
        for name, target in cases.items():
            with self.subTest(name):
                with self.assertRaises(notes_service.DocumentNotesError):
                    self.load(target)
                with self.assertRaises(notes_service.DocumentNotesError):
                    self.add(target, "no debe guardarse")
        self.assertEqual(self.rows(), [])
        # A relative path inside the root is the same document as its absolute path.
        self.assertEqual(self.load({"expediente_id": 42, "path": "titular/Pasaporte.pdf"})["identity"].ref,
                         self.load(self.exp(0))["identity"].ref)

    def test_link_escaping_the_root_is_rejected(self):
        outside = self.root / "outside"
        make_pdf(outside / "secreto.pdf", "secreto")
        link = self.exp_root / "enlace"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            if os.name != "nt":
                raise
            import _winapi  # Windows without symlink privilege: a directory junction.
            _winapi.CreateJunction(str(outside), str(link))

        def remove_link():
            try:
                os.unlink(link)
            except OSError:
                os.rmdir(link)

        self.addCleanup(remove_link)
        target = {"expediente_id": 42, "path": str(link / "secreto.pdf")}
        with self.assertRaises(notes_service.DocumentNotesError) as raised:
            self.add(target, "no debe guardarse")
        self.assertEqual(str(raised.exception), notes_service.OUTSIDE_ROOT)
        self.assertEqual(self.rows(), [])

    def test_replaced_file_does_not_inherit_notes(self):
        target = self.exp(0)
        first = self.load(target)["identity"]
        self.add(target, "nota sobre la versión 1", expected_sha256=first.content_sha256)
        make_pdf(self.exp_docs[0], "version 2 reemplazada")  # same name and folder
        self.snapshot()
        result = self.load(target)
        self.assertEqual(result["identity"].ref, first.ref)
        self.assertNotEqual(result["identity"].content_sha256, first.content_sha256)
        self.assertEqual((result["notes"], result["other_revisions"]), ([], 1))
        # A note typed while viewing the old version is not attributed to the new file.
        with self.assertRaises(notes_service.DocumentNotesError) as raised:
            self.add(target, "basada en la versión anterior", expected_sha256=first.content_sha256)
        self.assertEqual(str(raised.exception), notes_service.CHANGED)
        self.assertEqual(len(self.rows()), 1)
        self.add(target, "nota sobre la versión 2", expected_sha256=result["identity"].content_sha256)
        self.assertEqual(self.bodies(target), ["nota sobre la versión 2"])


class ActorAndContentTests(NotesBase):
    def test_only_real_active_session_users_can_read_or_write(self):
        target = self.exp(0)
        for actor in (None, {}, "ana", {"username": "ana"}, {"id": 99, "username": "fantasma"},
                      {"id": 3, "username": "baja"}, {"id": 1, "username": "luis"}, {"id": "uno"}):
            with self.subTest(actor=actor):
                with self.assertRaises(notes_service.DocumentNotesError):
                    notes_service.load_document_notes(actor, target, db_path=self.db)
                with self.assertRaises(notes_service.DocumentNotesError):
                    notes_service.add_document_note(actor, target, "x", request_id=uuid4().hex,
                                                    db_path=self.db)
        self.assertEqual(self.rows(), [])
        # The stored author comes from ``users``, never from the caller's text.
        note = notes_service.add_document_note({"id": 2}, target, "firmada", request_id=uuid4().hex,
                                               db_path=self.db)
        self.assertEqual((note["author_user_id"], note["author_username"]), (2, "luis"))

    def test_server_utc_timestamp_and_state(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        note = self.add(self.exp(1), "hora")
        after = datetime.now(timezone.utc)
        created = datetime.fromisoformat(note["created_at"])
        self.assertEqual(created.utcoffset(), timedelta(0))
        self.assertTrue(before <= created <= after, note["created_at"])
        self.assertEqual(note["status"], "active")
        self.assertEqual(len(note["content_sha256"]), 64)

    def test_body_validation_unicode_and_multiline(self):
        target = self.inbox(1)
        maximum = notes_service.MAX_NOTE_LENGTH
        for body in ("", "   \n\t ", None, "x" * (maximum + 1), "con\x00nulo", "campana\x07"):
            with self.subTest(body=repr(body)[:30]):
                with self.assertRaises(notes_service.DocumentNotesError):
                    self.add(target, body)
        self.assertEqual(self.rows(), [])
        text = "  Ñandú · 漢字 · 🚀 <b>no es HTML</b> & 'comillas'\r\nlínea 2\rlínea 3\n\tsangría  "
        note = self.add(target, text)
        self.assertEqual(note["body"],
                         "Ñandú · 漢字 · 🚀 <b>no es HTML</b> & 'comillas'\nlínea 2\nlínea 3\n\tsangría")
        self.assertEqual(len(self.add(target, "y" * maximum)["body"]), maximum)

    def test_double_submit_and_request_ids(self):
        target, request_id = self.exp(3), uuid4().hex
        first = self.add(target, "una vez", request_id=request_id)
        second = self.add(target, "una vez", request_id=request_id)
        self.assertEqual((first["created"], second["created"]), (True, False))
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.rows()), 1)
        # A reused request id never lands on another document, author or text.
        for other, body in ((self.exp(4), "una vez"), (target, "otro texto")):
            with self.assertRaises(notes_service.DocumentNotesError):
                self.add(other, body, request_id=request_id)
        with self.assertRaises(notes_service.DocumentNotesError):
            notes_service.add_document_note({"id": 2}, target, "una vez", request_id=request_id,
                                            db_path=self.db)
        for bad in ("", "corto", "con espacios 1234", "x" * 65, None):
            with self.subTest(request_id=bad), self.assertRaises(notes_service.DocumentNotesError):
                notes_service.add_document_note(self.actor, target, "válida", request_id=bad,
                                                db_path=self.db)
        self.assertEqual(len(self.rows()), 1)

    def test_missing_database_is_reported_and_never_created(self):
        missing = self.root / "no-existe.db"
        calls = (
            lambda: notes_service.load_document_notes(self.actor, self.exp(0), db_path=missing),
            lambda: notes_service.add_document_note(self.actor, self.exp(0), "x",
                                                    request_id=uuid4().hex, db_path=missing),
        )
        for call in calls:
            with self.assertRaises(notes_service.DocumentNotesError) as raised:
                call()
            self.assertEqual(str(raised.exception), notes_service.DB_UNAVAILABLE)
        self.assertFalse(missing.exists())

    def test_notes_persist_across_a_service_restart(self):
        self.add(self.exp(0), "persistente")
        self.add(self.inbox(2), "persistente en bandeja")
        importlib.reload(repository)
        importlib.reload(notes_service)
        self.assertEqual(self.bodies(self.exp(0)), ["persistente"])
        self.assertEqual(self.bodies(self.inbox(2)), ["persistente en bandeja"])
        self.assertEqual(self.bodies(self.exp(1)), [])


class ActivityTests(NotesBase):
    def test_inbox_activity_reads_existing_events_and_keeps_description_apart(self):
        result = self.load(self.inbox(1))
        document_inbox_service.get_inbox_events.assert_called_with(1)
        self.assertEqual(result["activity"], [{"at": "2026-11-08 10:15:00", "type": "imported",
                                               "message": "Documento importado", "source": "Bandeja"}])
        self.assertEqual(result["identity"].description, "Descripción de bandeja")
        self.assertEqual(result["notes"], [])
        self.add(self.inbox(1), "nota personal")
        result = self.load(self.inbox(1))
        self.assertEqual([note["body"] for note in result["notes"]], ["nota personal"])
        # Adding a note creates no Bandeja event and leaves the item's own ``notes`` alone.
        self.assertEqual(len(result["activity"]), 1)
        self.assertEqual(result["identity"].description, "Descripción de bandeja")
        self.assertEqual(self.load(self.inbox(2))["activity"], [])

    def test_expedient_activity_is_only_the_real_file_date(self):
        result = self.load(self.exp(2))
        expected = datetime.fromtimestamp(self.exp_docs[2].stat().st_mtime).isoformat(timespec="seconds")
        self.assertEqual(result["activity"], [{"at": expected, "type": "file_modified",
                                               "message": "Última modificación del archivo",
                                               "source": "Sistema de archivos"}])
        self.assertIsNone(result["activity_error"])
        document_inbox_service.get_inbox_events.assert_not_called()

    def test_activity_failure_keeps_notes_visible(self):
        self.add(self.inbox(1), "visible")
        document_inbox_service.get_inbox_events.side_effect = RuntimeError("bloqueada")
        result = self.load(self.inbox(1))
        self.assertEqual(result["activity"], [])
        self.assertEqual(result["activity_error"], "No se pudo leer la actividad de Bandeja.")
        self.assertEqual([note["body"] for note in result["notes"]], ["visible"])


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def database(self, name, script=""):
        path = self.root / name
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(script)
        return path

    def test_clean_install_is_idempotent(self):
        db = self.database("clean.db")
        repository.ensure_schema(db_path=db)
        repository.ensure_schema(db_path=db)
        with closing(sqlite3.connect(db)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
            columns = [row[1] for row in conn.execute("PRAGMA table_info(document_viewer_notes)")]
        self.assertEqual(tables - {"sqlite_sequence"}, {"document_viewer_notes"})
        self.assertIn("idx_document_viewer_notes_document", indexes)
        self.assertEqual(columns, NOTE_COLUMNS)

    def test_incremental_migration_preserves_existing_data(self):
        db = self.database("existing.db", USERS_SQL + """
            CREATE TABLE document_inbox_items (id INTEGER PRIMARY KEY, original_filename TEXT, notes TEXT);
            INSERT INTO document_inbox_items VALUES (1, 'Pasaporte.pdf', 'Descripción');
        """)
        repository.ensure_schema(db_path=db)
        repository.insert_note({
            "document_kind": "inbox", "document_ref": "inbox:1", "inbox_item_id": 1,
            "content_sha256": "a" * 64, "size_bytes": 10, "body": "previa",
            "author_user_id": 1, "author_username": "ana", "request_id": uuid4().hex,
            "created_at": "2026-11-09T10:00:00+00:00",
        }, db_path=db)
        with closing(sqlite3.connect(db)) as conn:
            before = list(conn.iterdump())
        repository.ensure_schema(db_path=db)
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(list(conn.iterdump()), before)
            self.assertEqual(conn.execute("SELECT notes FROM document_inbox_items").fetchall(),
                             [("Descripción",)])

    def test_migration_is_additive_and_isolated(self):
        sql = repository.MIGRATION_PATH.read_text(encoding="utf-8")
        statements = re.sub(r"--[^\n]*", "", sql).upper()
        for forbidden in ("DROP ", "ALTER ", "DELETE ", "UPDATE ", "INSERT ", "REPLACE ", "PRAGMA", "ATTACH"):
            self.assertNotIn(forbidden, statements)
        created = re.findall(r"CREATE\s+(?:TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\s+(\w+)", statements)
        self.assertEqual(created, ["DOCUMENT_VIEWER_NOTES", "IDX_DOCUMENT_VIEWER_NOTES_DOCUMENT"])
        self.assertEqual(statements.count("CREATE "), 2)
        dated = sorted(p.name for p in repository.MIGRATION_PATH.parent.glob("20261109*"))
        self.assertEqual(dated, ["20261109_01_create_document_viewer_notes.sql"])

    def test_database_constraints_reject_invalid_rows(self):
        db = self.database("checks.db")
        repository.ensure_schema(db_path=db)
        base = ("inbox", "inbox:1", 1, None, None, "b" * 64, 1, "texto", 1, "ana", "active",
                uuid4().hex, "2026-11-09T10:00:00+00:00")
        invalid = {
            "blank body": {7: "   "},
            "long body": {7: "z" * 4001},
            "unknown kind": {0: "pdf"},
            "inbox without item": {2: None},
            "expedient without path": {0: "expedient", 3: 42},
            "unknown status": {10: "deleted"},
            "short fingerprint": {5: "abc"},
        }
        with closing(sqlite3.connect(db)) as conn:
            for name, changes in invalid.items():
                values = list(base)
                for index, value in changes.items():
                    values[index] = value
                values[11] = uuid4().hex
                with self.subTest(name), self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO document_viewer_notes (document_kind, document_ref, inbox_item_id, "
                        "expediente_id, relative_path, content_sha256, size_bytes, body, author_user_id, "
                        "author_username, status, request_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM document_viewer_notes").fetchone()[0], 0)

    def test_flet_layers_hold_no_sql_or_schema(self):
        for path in FLET_SOURCES:
            source = path.read_text(encoding="utf-8")
            for forbidden in ("CREATE TABLE", "executescript", "INSERT INTO", "sqlite3",
                              "document_viewer_notes_repository", "ensure_schema"):
                self.assertNotIn(forbidden, source, (path.name, forbidden))
        # Same rule as the DV22 CI contract: no DB module within one import hop.
        notes_ui = FLET_SOURCES[0]
        modules = imported_modules(notes_ui)
        self.assertEqual(sorted(m for m in modules if is_db_module(m)), [])
        for module in sorted(m for m in modules if m.startswith("backend.")):
            target = REPO_ROOT / (module.replace(".", "/") + ".py")
            if target.is_file():
                self.assertEqual(sorted(m for m in imported_modules(target) if is_db_module(m)), [], module)
        for view in (EXPEDIENTS, INBOX):
            source = view.read_text(encoding="utf-8")
            self.assertNotIn("document_viewer_notes_service", source)
            self.assertNotIn("document_viewer_notes_repository", source)


class PanelBase(NotesBase):
    def setUp(self):
        super().setUp()
        self.patch(viewer_service, "PREVIEW_DIR", self.root / "previews")
        self.page = SimpleNamespace(overlay=[], update=Mock())

    def notes(self, run=None, **kwargs):
        kwargs.setdefault("actor", self.actor)
        return panel.ViewerNotes(db_path=self.db, run=run or (lambda work: work()), **kwargs)

    def open_expedient(self, index=0, notes=None):
        queue = [{"path": str(path), "name": path.name} for path in self.exp_docs]
        return open_document_viewer_modal(
            self.page, queue[index]["path"], title=queue[index]["name"], expediente_id=42,
            queue=queue, queue_index=index, near_window=0, notes=notes or self.notes())

    @staticmethod
    def run_jobs(jobs):
        while jobs:
            jobs.pop(0)()

    def controller(self, dialog):
        return viewer_layout(dialog).notes

    def texts(self, dialog):
        return [c.value for c in walk(self.controller(dialog).container) if isinstance(c, ft.Text)]

    def note_bodies(self, dialog):
        return [card.content.controls[1].value for card in self.controller(dialog).note_cards]

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def compare(self, dialog):
        self.button(dialog, "Comparador 4").on_click(None)
        return viewer_layout(dialog)


class NotesPanelTests(PanelBase):
    def test_without_notes_the_viewer_shell_is_unchanged(self):
        queue = [{"path": str(path), "name": path.name} for path in self.exp_docs]
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], expediente_id=42, queue=queue,
                                            near_window=0)
        layout = viewer_layout(dialog)
        self.assertIsNone(layout.notes)
        self.assertIs(dialog.content.content.controls[-1], layout.canvas)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.rows(), [])

    def test_panel_follows_the_active_document_in_single_and_compare_modes(self):
        for index in range(4):
            self.add(self.exp(index), f"nota de {index}")
        dialog = self.open_expedient()
        layout = viewer_layout(dialog)
        area = dialog.content.content.controls[-1]
        self.assertIsInstance(area, ft.Row)
        self.assertEqual(len(area.controls), 2)
        self.assertIs(area.controls[0], layout.canvas)
        self.assertIs(area.controls[1], layout.notes.container)
        self.assertEqual(self.note_bodies(dialog), ["nota de 0"])
        texts = self.texts(dialog)
        self.assertIn("Notas y actividad", texts)
        self.assertIn("Pasaporte.pdf", texts)
        self.assertIn("Última modificación del archivo", texts)
        self.assertIn("Autor: ana (sesión actual)", texts)
        # Same name, other folder: other notes.
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(self.note_bodies(dialog), ["nota de 1"])
        layout = self.compare(dialog)
        self.assertEqual(self.note_bodies(dialog), ["nota de 1"])
        layout.tiles[2].container.on_click(None)
        self.assertEqual(self.note_bodies(dialog), ["nota de 2"])
        self.button(dialog, "Grupo siguiente").on_click(None)
        self.assertEqual(viewer_layout(dialog).document.index, 4)
        self.assertEqual(self.note_bodies(dialog), [])
        self.assertIn("Todavía no hay notas para este documento.", self.texts(dialog))
        self.button(dialog, "Grupo anterior").on_click(None)
        self.assertEqual(self.note_bodies(dialog), ["nota de 0"])
        self.button(dialog, "Documento único").on_click(None)
        self.assertEqual(self.note_bodies(dialog), ["nota de 0"])
        self.button(dialog, "Cerrar").on_click(None)

    def test_add_note_from_panel_and_find_it_after_reopening(self):
        dialog = self.open_expedient(1)
        controller = self.controller(dialog)
        controller.field.value = "Revisar firma\nsegunda línea"
        controller.field.on_change(SimpleNamespace(control=controller.field))
        controller.send_button.on_click(None)
        self.assertEqual(self.note_bodies(dialog), ["Revisar firma\nsegunda línea"])
        self.assertEqual(controller.feedback_text.value, "Nota añadida.")
        self.assertEqual(controller.field.value, "")
        self.assertIn("ana", self.texts(dialog))
        # Empty submission: visible error, nothing written.
        controller.send_button.on_click(None)
        self.assertEqual(controller.feedback_text.value, "La nota está vacía.")
        # Cancel clears the draft and the message.
        controller.field.value = "borrador"
        controller.field.on_change(SimpleNamespace(control=controller.field))
        controller.cancel_button.on_click(None)
        self.assertEqual((controller.field.value, controller.feedback_text), ("", None))
        self.assertEqual(len(self.rows()), 1)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual((self.bodies(self.exp(0)), self.bodies(self.exp(2))), ([], []))
        reopened = self.open_expedient(1)
        self.assertEqual(self.note_bodies(reopened), ["Revisar firma\nsegunda línea"])
        self.button(reopened, "Cerrar").on_click(None)

    def test_double_click_and_retry_never_duplicate(self):
        jobs = []
        dialog = self.open_expedient(0, notes=self.notes(run=jobs.append))
        self.run_jobs(jobs)
        controller = self.controller(dialog)
        controller.field.value = "doble clic"
        send = controller.send_button
        send.on_click(None)
        send.on_click(None)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(controller.send_button.disabled)
        self.assertEqual(viewer_action_label(controller.send_button), "Enviando…")
        self.run_jobs(jobs)
        self.assertEqual(len(self.rows()), 1)
        # The first attempt writes but reports an error; the retry reuses its request id.
        real, request_ids = notes_service.add_document_note, []

        def flaky(*args, **kwargs):
            note = real(*args, **kwargs)
            request_ids.append(kwargs["request_id"])
            if len(request_ids) == 1:
                raise notes_service.DocumentNotesError("Conexión interrumpida.")
            return note

        with patch.object(notes_service, "add_document_note", side_effect=flaky):
            controller.field.value = "reintento"
            controller.send_button.on_click(None)
            self.run_jobs(jobs)
            self.assertEqual(controller.feedback_text.value, "Conexión interrumpida.")
            self.assertEqual(controller.field.value, "reintento")
            controller.send_button.on_click(None)
            self.run_jobs(jobs)
        self.assertEqual(request_ids[0], request_ids[1])
        self.assertEqual([row["body"] for row in self.rows()], ["doble clic", "reintento"])
        self.assertEqual(self.note_bodies(dialog), ["reintento", "doble clic"])
        self.button(dialog, "Cerrar").on_click(None)

    def test_loading_never_blocks_viewer_commands(self):
        jobs = []
        dialog = self.open_expedient(0, notes=self.notes(run=jobs.append))
        self.assertIn("Cargando notas…", self.texts(dialog))
        self.button(dialog, "Zoom +").on_click(None)
        self.assertEqual(viewer_layout(dialog).zoom_label.value, "Zoom: 2.0x")
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(len(jobs), 2)  # one load per visited document, none repeated
        self.run_jobs(jobs)
        controller = self.controller(dialog)
        self.assertEqual(controller.key, f"expedient:42:{self.exp_docs[1]}")
        self.assertEqual(controller.state.status, panel.READY)
        self.button(dialog, "Cerrar").on_click(None)

    def test_close_drops_pending_results(self):
        jobs = []
        dialog = self.open_expedient(0, notes=self.notes(run=jobs.append))
        controller = self.controller(dialog)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertTrue(controller.closed)
        flushes = self.page.update.call_count
        self.run_jobs(jobs)  # the load finishes after the viewer closed
        self.assertEqual(self.page.update.call_count, flushes)
        self.assertIsNone(dialog.content)
        self.assertEqual(controller.state.status, panel.LOADING)

    def test_missing_identity_or_actor_is_visible_and_writes_nothing(self):
        # A Bandeja queue without item ids has no trustworthy identity.
        queue = [{"path": str(path), "name": "Pasaporte.pdf"} for path in self.inbox_docs]
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], queue=queue, near_window=0,
                                            notes=self.notes())
        self.assertIn(notes_service.NO_IDENTITY, self.texts(dialog))
        self.assertIsNone(self.controller(dialog).send_button)
        self.button(dialog, "Cerrar").on_click(None)
        dialog = self.open_expedient(0, notes=self.notes(actor=None))
        self.assertIn(notes_service.NO_ACTOR, self.texts(dialog))
        self.assertIsNone(self.controller(dialog).send_button)
        self.assertIsNotNone(self.controller(dialog).retry_button)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.rows(), [])

    def test_panel_folds_and_the_mosaic_reflows(self):
        self.add(self.exp(0), "plegable")
        dialog = self.open_expedient()
        layout = viewer_layout(dialog)
        controller = layout.notes
        width = panel.COMPACT_PANEL_WIDTH if layout.metrics.compact else panel.PANEL_WIDTH
        self.assertEqual(controller.container.width, width)
        self.assertTrue(layout.canvas.expand)
        layout = self.compare(dialog)
        content = layout.metrics.content_width
        self.assertEqual(layout.tiles[0].container.width, (content - width - panel.GAP - 10) // 2)
        controller.toggle_button.on_click(None)
        layout = viewer_layout(dialog)
        self.assertTrue(controller.collapsed)
        self.assertEqual(layout.notes.container.width, panel.RAIL_WIDTH)
        self.assertEqual(layout.tiles[0].container.width,
                         (content - panel.RAIL_WIDTH - panel.GAP - 10) // 2)
        controller.toggle_button.on_click(None)
        self.assertFalse(controller.collapsed)
        self.assertEqual(self.note_bodies(dialog), ["plegable"])
        self.button(dialog, "Cerrar").on_click(None)


class ViewWiringTests(PanelBase):
    def test_inbox_view_resolves_each_document_by_its_item(self):
        self.add(self.inbox(3), "solo del ítem 3")
        state = {"selected_item_id": 2, "selected_item_ids": set(),
                 "items": [copy.deepcopy(item) for item in self.items.values()],
                 "viewer_notes": self.notes()}
        show_error = Mock()
        scope = bind(INBOX, ("selected_item", "inbox_viewer_options", "show_preview"), dict(
            page=self.page, state=state, open_document_viewer_modal=open_document_viewer_modal,
            document_inbox_service=document_inbox_service, show_error=show_error,
            pdf_toolbar_for_item=lambda item, queue=(): None,
        ))
        scope["show_preview"]()
        dialog = self.page.overlay[-1]
        self.assertEqual(self.note_bodies(dialog), [])
        self.assertIn("Bandeja · documento #2", self.texts(dialog))
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(self.note_bodies(dialog), ["solo del ítem 3"])
        layout = self.compare(dialog)
        layout.tiles[0].container.on_click(None)
        texts = self.texts(dialog)
        self.assertIn("Bandeja · documento #1", texts)
        self.assertIn("Documento importado", texts)
        self.assertIn("08/11/2026 10:15 · Bandeja", texts)
        self.assertIn("Descripción de Bandeja: Descripción de bandeja", texts)
        self.assertEqual(self.note_bodies(dialog), [])
        self.button(dialog, "Cerrar").on_click(None)
        # A single item opens without a queue and keeps its identity.
        state.update(items=[copy.deepcopy(self.items[1])], selected_item_id=1)
        scope["show_preview"]()
        dialog = self.page.overlay[-1]
        self.assertIn("Bandeja · documento #1", self.texts(dialog))
        self.button(dialog, "Cerrar").on_click(None)
        show_error.assert_not_called()

    def test_expedients_view_passes_the_session_notes(self):
        notes, canonical = self.notes(), Mock()
        scope = bind(EXPEDIENTS, ("show_document_preview",), dict(
            page=self.page, state={"dialog_expediente_id": 42, "viewer_notes": notes},
            show_form_error=Mock(), open_document_viewer_modal=canonical, document_viewer_dialog=None,
        ))
        scope["show_document_preview"](str(self.exp_docs[0]))
        self.assertIs(canonical.call_args.kwargs["notes"], notes)
        self.assertEqual(canonical.call_args.kwargs["expediente_id"], 42)

    def test_views_and_main_inject_the_authenticated_user(self):
        for view, name in ((EXPEDIENTS, "expedients_view"), (INBOX, "document_inbox_view")):
            tree = ast.parse(view.read_text(encoding="utf-8"))
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            arguments = function.args.args + function.args.kwonlyargs
            self.assertEqual(arguments[-1].arg, "current_user")
            self.assertIn("ViewerNotes(actor=current_user)", ast.unparse(function))
        calls = {ast.unparse(n.func): n for n in ast.walk(ast.parse(MAIN.read_text(encoding="utf-8")))
                 if isinstance(n, ast.Call) and ast.unparse(n.func) in ("expedients_view", "document_inbox_view")}
        self.assertEqual(set(calls), {"expedients_view", "document_inbox_view"})
        for call in calls.values():
            keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
            self.assertEqual(keywords["current_user"], "current_user.get('value')")


if __name__ == "__main__":
    unittest.main()
