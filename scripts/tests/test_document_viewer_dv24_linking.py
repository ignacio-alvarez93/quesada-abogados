"""WO-DV24-P3: logical link of viewer documents to expedientes.

Synthetic PDFs and a synthetic SQLite CRM in a TemporaryDirectory only. The
operational database path is redirected to that file, so the canonical
``document_inbox_service.link_inbox_item`` and ``get_inbox_item`` run for
real against it (one commit per item). Bandeja directories are never
created, CRM selectors are read-only fakes over the same file, and every
other Bandeja/Box mutation is patched to fail the test if it is called.
"""
import ast
import copy
import gc
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import fitz
import flet as ft

from backend.services import document_inbox_service
from backend.services import document_viewer_link_service as link_service
from backend.services import document_viewer_notes_service as notes_service
from backend.services import document_viewer_service as viewer_service
from database import connection
from frontend.components import document_viewer_link_dialog as link_dialog
from frontend.components import document_viewer_notes_panel as panel
from frontend.components.document_viewer_link_dialog import ViewerLinking
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label, viewer_layout,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE = REPO_ROOT / "backend" / "services" / "document_viewer_link_service.py"
DIALOG = REPO_ROOT / "frontend" / "components" / "document_viewer_link_dialog.py"
EXPEDIENTS = REPO_ROOT / "frontend" / "views" / "expedients_view.py"
INBOX = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"

CRM_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO users (id, username, password_hash, is_active)
VALUES (1, 'ana', 'x', 1), (2, 'luis', 'x', 1), (3, 'baja', 'x', 0);
CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT, activo INTEGER DEFAULT 1);
INSERT INTO clientes VALUES (7, 'Cliente Siete', 1), (8, 'Cliente Ocho', 1);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY, cliente_id INTEGER, numero_expediente TEXT, activo INTEGER DEFAULT 1
);
INSERT INTO expedientes VALUES
    (42, 7, 'EXP-42', 1), (43, 7, 'EXP-43', 1), (50, 8, 'EXP-50', 1),
    (51, 7, 'EXP-51', 0), (52, NULL, 'EXP-52', 1);
"""
# id: (status, client_id, expedient_id, metadata_json)
ITEMS = {
    1: ("pending", 7, None, None),
    2: ("pending", 7, None, None),
    3: ("pending", None, None, None),
    4: ("linked", 7, 43, None),
    5: ("discarded", 7, None, None),
    6: ("linked", 7, 42, None),
    7: ("copied_to_box", 7, 43, None),
    8: ("pending", 7, None, '{"duplicate_of_id": 1, "duplicate_reason": "sha256"}'),
}
# Every Bandeja/Box write except the canonical link.
FORBIDDEN = ("update_inbox_item_status", "update_inbox_item_filename", "import_file_to_inbox",
             "copy_inbox_item_to_expedient_box", "copy_document_inbox_batch_to_expedient_box",
             "import_box_file_to_inbox", "bulk_import_box_files_to_inbox",
             "create_document_inbox_batch", "add_items_to_document_inbox_batch",
             "mark_detected_inbox_duplicates", "open_inbox_item")
TARGET = "EXP-42 (#42)"


def make_pdf(path, pages=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        for number in range(pages):
            document.new_page(width=150, height=150).insert_text((20, 30), f"{path.stem} p{number + 1}")
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
    return modules


class LinkBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # The canonical inbox service uses ``with get_connection() as conn``, which commits but
        # never closes; a sqlite3 connection is only freed by the cyclic GC (it is referenced by
        # its own statement cache). On Windows the open handle locks crm.db and the cleanup
        # fails, so collect right before removing the directory (cleanups run LIFO).
        self.addCleanup(gc.collect)
        self.root = Path(temp.name)
        self.db = self.root / "crm.db"
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(CRM_SQL)
        self.patch(connection, "DB_PATH", str(self.db))
        # The canonical schema helper would create data/document_inbox in the repo.
        self.patch(document_inbox_service, "_ensure_dirs")
        document_inbox_service.ensure_document_inbox_schema()
        self.actor = {"id": 1, "username": "ana"}

        self.inbox_docs = {item_id: self.root / "inbox" / f"{item_id}_Pasaporte.pdf" for item_id in ITEMS}
        self.exp_docs = [self.root / "box" / "EXP-42" / name for name in ("Contrato.pdf", "Nomina.pdf")]
        for path in [*self.inbox_docs.values(), *self.exp_docs]:
            make_pdf(path)
        with closing(sqlite3.connect(self.db)) as conn:
            for item_id, (status, client_id, expedient_id, metadata) in ITEMS.items():
                path = self.inbox_docs[item_id]
                conn.execute(
                    "INSERT INTO document_inbox_items (id, original_filename, stored_filename, "
                    "stored_path, status, client_id, expedient_id, notes, sha256, metadata_json, "
                    "updated_at) VALUES (?, 'Pasaporte.pdf', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item_id, path.name, str(path), status, client_id, expedient_id,
                     f"descripción {item_id}", f"{item_id:064d}", metadata, "2026-11-01 10:00:00"))
            conn.commit()
        self.files = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                      for path in [*self.inbox_docs.values(), *self.exp_docs]}

        self.canonical = document_inbox_service.link_inbox_item
        self.link = self.patch(document_inbox_service, "link_inbox_item", wraps=self.canonical)
        self.patch(document_inbox_service, "get_expedient", side_effect=self.expedient)
        self.patch(document_inbox_service, "client_autocomplete_options", side_effect=self.client_options)
        self.patch(document_inbox_service, "expedient_autocomplete_options_for_client",
                   side_effect=self.expedient_options)
        self.forbidden = {name: self.patch(document_inbox_service, name, side_effect=AssertionError(name))
                          for name in FORBIDDEN}

    def tearDown(self):
        # Linking never touches files, never creates Bandeja items and never copies or imports.
        for path, (data, mtime) in self.files.items():
            self.assertEqual(path.read_bytes(), data, path)
            self.assertEqual(path.stat().st_mtime_ns, mtime, path)
        self.assertTrue({row["id"] for row in self.rows()} <= set(ITEMS))
        for name, mock in self.forbidden.items():
            self.assertEqual(mock.call_count, 0, name)
        self.assertFalse((self.root / "box" / "EXP-42" / "Pasaporte.pdf").exists())
        self.assertEqual(sorted(p.name for p in (self.root / "box" / "EXP-42").iterdir()),
                         ["Contrato.pdf", "Nomina.pdf"])

    def patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    # ------------------------------------------------------------------ synthetic CRM

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params)]

    def execute(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute(sql, params)
            conn.commit()

    def expedient(self, expedient_id):
        rows = self.query("SELECT * FROM expedientes WHERE id = ?", (int(expedient_id),))
        return rows[0] if rows else {}

    def client_options(self):
        return [{"id": row["id"], "label": row["nombre"]}
                for row in self.query("SELECT * FROM clientes WHERE activo = 1 ORDER BY id")]

    def expedient_options(self, client_id):
        return [{"id": row["id"], "label": f"#{row['id']} · {row['numero_expediente']}"}
                for row in self.query("SELECT * FROM expedientes WHERE cliente_id = ? ORDER BY id",
                                      (int(client_id),))]

    def rows(self):
        return self.query("SELECT * FROM document_inbox_items ORDER BY id")

    def row(self, item_id):
        return next(row for row in self.rows() if row["id"] == item_id)

    def events(self, item_id=None):
        sql = "SELECT item_id, event_type, message, metadata_json FROM document_inbox_events"
        rows = self.query(sql + " ORDER BY id")
        return [row for row in rows if item_id is None or row["item_id"] == item_id]

    # ------------------------------------------------------------------ requests

    def doc(self, item_id, path=None):
        path = path or self.inbox_docs.get(item_id) or self.inbox_docs[1]
        return {"key": f"inbox:{item_id}", "name": "Pasaporte.pdf", "path": str(path),
                "inbox_item_id": item_id}

    def box_doc(self, index=0):
        path = self.exp_docs[index]
        return {"key": f"expedient:42:{path}", "name": path.name, "path": str(path)}

    def prepare(self, documents, client_id=7, expedient_id=42, actor=None):
        return link_service.prepare_link(actor or self.actor, documents, client_id=client_id,
                                         expedient_id=expedient_id, db_path=self.db)

    def link_now(self, documents, client_id=7, expedient_id=42, **kwargs):
        kwargs.setdefault("confirmed", True)
        return link_service.link_documents(self.actor, documents, client_id=client_id,
                                           expedient_id=expedient_id, db_path=self.db, **kwargs)

    @staticmethod
    def statuses(result):
        return {item.inbox_item_id: item.status for item in result.items}


class SingleLinkTests(LinkBase):
    def test_single_link_reuses_the_canonical_service_and_is_logical_only(self):
        before = self.row(1)
        result = self.link_now([self.doc(1)])
        self.link.assert_called_once_with(1, client_id=7, expedient_id=42)
        self.assertEqual(self.statuses(result), {1: link_service.LINKED})
        self.assertEqual(result.items[0].message, f"Vinculado al expediente {TARGET}.")
        self.assertEqual((result.user, result.target.label), ({"id": 1, "username": "ana"}, TARGET))
        after = self.row(1)
        self.assertEqual((after["client_id"], after["expedient_id"], after["status"]), (7, 42, "linked"))
        # Only the link fields move: no copy to Box, no new path, the description stays.
        for column in ("stored_path", "stored_filename", "original_filename", "linked_document_path",
                       "copied_to_box_path", "copied_to_box_at", "notes", "sha256", "metadata_json"):
            self.assertEqual(after[column], before[column], column)
        self.assertIsNone(after["copied_to_box_path"])
        self.assertEqual([(e["event_type"], e["message"]) for e in self.events(1)],
                         [("linked", "Documento vinculado")])
        self.assertEqual(self.events(2), [])

    def test_client_expedient_relationship_is_enforced_by_the_application_layer(self):
        # Evidence: the canonical service accepts a client that does not own the expediente.
        self.canonical(3, client_id=8, expedient_id=42)
        self.assertEqual((self.row(3)["client_id"], self.row(3)["expedient_id"]), (8, 42))
        self.execute("UPDATE document_inbox_items SET client_id = NULL, expedient_id = NULL, "
                     "status = 'pending' WHERE id = 3")
        self.execute("DELETE FROM document_inbox_events WHERE item_id = 3")
        before = self.rows()
        cases = {
            "client does not own expediente": (8, 42, "no pertenece al cliente seleccionado"),
            "expediente missing": (7, 999, "no existe"),
            "expediente without client": (7, 52, "no tiene cliente asignado"),
            "expediente archived": (7, 51, "archivado"),
            "no client": (None, 42, "Selecciona un cliente."),
            "invalid expediente": (7, "abc", "Selecciona un expediente."),
            "negative expediente": (7, -42, "Selecciona un expediente."),
        }
        for name, (client_id, expedient_id, message) in cases.items():
            with self.subTest(name), self.assertRaises(link_service.DocumentLinkError) as raised:
                self.link_now([self.doc(1)], client_id=client_id, expedient_id=expedient_id)
            self.assertIn(message, str(raised.exception))
        self.link.assert_not_called()
        self.assertEqual(self.rows(), before)

    def test_item_identity_and_path_are_verified(self):
        before = self.rows()
        result = self.link_now([
            self.doc(99),                                  # deleted / never existed
            self.doc(1, path=self.inbox_docs[2]),          # another item's file
            self.doc(2, path=self.root / "fuera.pdf"),     # missing file
            {"key": "x", "path": str(self.inbox_docs[3]), "inbox_item_id": "tres"},
        ])
        messages = [(item.status, item.message) for item in result.items]
        self.assertEqual(messages, [
            (link_service.REJECTED, link_service.ITEM_MISSING),
            (link_service.REJECTED, link_service.WRONG_FILE),
            (link_service.REJECTED, link_service.WRONG_FILE),
            (link_service.NOT_LINKABLE, link_service.NOT_LINKABLE_MESSAGE),
        ])
        self.link.assert_not_called()
        self.assertEqual(self.rows(), before)

    def test_item_deleted_after_review_is_not_linked(self):
        plan = self.prepare([self.doc(1), self.doc(2)])
        self.execute("DELETE FROM document_inbox_items WHERE id = 2")
        result = link_service.execute_link(plan, confirmed=True)
        self.assertEqual(self.statuses(result), {1: link_service.LINKED, 2: link_service.REJECTED})
        self.assertEqual(result.items[1].message, link_service.ITEM_MISSING)
        self.link.assert_called_once_with(1, client_id=7, expedient_id=42)

    def test_previous_link_to_another_expediente_needs_special_confirmation(self):
        plan = self.prepare([self.doc(4)])
        self.assertEqual(plan.checks[0].outcome, link_service.TRANSFER)
        self.assertIn("#43", plan.checks[0].message)
        result = link_service.execute_link(plan, confirmed=True)
        self.assertEqual(self.statuses(result), {4: link_service.REJECTED})
        self.assertIn("No confirmado", result.items[0].message)
        self.assertEqual(self.row(4)["expedient_id"], 43)
        self.link.assert_not_called()
        # Another client's item is a transfer too.
        self.assertEqual(self.prepare([self.doc(1)], client_id=8, expedient_id=50).checks[0].outcome,
                         link_service.TRANSFER)
        # With the special confirmation the canonical link moves it.
        result = self.link_now([self.doc(4)], allow_transfer=True)
        self.assertEqual(self.statuses(result), {4: link_service.LINKED})
        self.assertEqual(self.row(4)["expedient_id"], 42)

    def test_discarded_duplicate_and_copied_items_are_never_relinked(self):
        before = self.rows()
        result = self.link_now([self.doc(5), self.doc(8), self.doc(7)], allow_transfer=True)
        self.assertEqual(self.statuses(result), {5: link_service.REJECTED, 8: link_service.REJECTED,
                                                 7: link_service.REJECTED})
        self.assertIn("Descartado", result.items[0].message)
        self.assertIn("duplicado del documento #1", result.items[1].message)
        self.assertIn("copiado a Box", result.items[2].message)
        self.link.assert_not_called()
        self.assertEqual(self.rows(), before)

    def test_idempotency_and_single_execution_of_a_plan(self):
        result = self.link_now([self.doc(6)])
        self.assertEqual(self.statuses(result), {6: link_service.UNCHANGED})
        self.link.assert_not_called()
        plan = self.prepare([self.doc(1)])
        first = link_service.execute_link(plan, confirmed=True)
        again = link_service.execute_link(plan, confirmed=True)
        self.assertIs(first, again)
        self.assertEqual(self.link.call_count, 1)
        second = self.link_now([self.doc(1)])
        self.assertEqual(self.statuses(second), {1: link_service.UNCHANGED})
        self.assertEqual(self.link.call_count, 1)
        self.assertEqual(len(self.events(1)), 1)

    def test_confirmation_and_session_user_are_required(self):
        before = self.rows()
        plan = self.prepare([self.doc(1)])
        for confirmed in (False, None, "sí", 1):
            with self.subTest(confirmed=confirmed), self.assertRaises(link_service.DocumentLinkError) as raised:
                link_service.execute_link(plan, confirmed=confirmed)
            self.assertEqual(str(raised.exception), link_service.NOT_CONFIRMED)
        with self.assertRaises(link_service.DocumentLinkError):
            link_service.execute_link({"checks": []}, confirmed=True)
        for actor, message in ((None, link_service.NO_ACTOR), ({"id": 99}, link_service.NOT_AUTHORIZED),
                               ({"id": 3, "username": "baja"}, link_service.NOT_AUTHORIZED),
                               ({"id": 1, "username": "luis"}, link_service.NOT_AUTHORIZED)):
            with self.subTest(actor=actor), self.assertRaises(link_service.DocumentLinkError) as raised:
                link_service.prepare_link(actor, [self.doc(1)], client_id=7, expedient_id=42,
                                          db_path=self.db)
            self.assertEqual(str(raised.exception), message)
        # The user is deactivated between review and confirmation.
        self.execute("UPDATE users SET is_active = 0 WHERE id = 1")
        with self.assertRaises(link_service.DocumentLinkError) as raised:
            link_service.execute_link(plan, confirmed=True)
        self.assertEqual(str(raised.exception), link_service.NOT_AUTHORIZED)
        self.link.assert_not_called()
        self.assertEqual(self.rows(), before)

    def test_expediente_changed_after_review_blocks_the_whole_operation(self):
        plan = self.prepare([self.doc(1), self.doc(2)])
        self.execute("UPDATE expedientes SET cliente_id = 8 WHERE id = 42")
        with self.assertRaises(link_service.DocumentLinkError):
            link_service.execute_link(plan, confirmed=True)
        self.execute("UPDATE expedientes SET cliente_id = 7, activo = 0 WHERE id = 42")
        with self.assertRaises(link_service.DocumentLinkError):
            link_service.execute_link(plan, confirmed=True)
        self.link.assert_not_called()
        self.assertIsNone(plan.result)

    def test_box_only_documents_are_reported_without_any_write(self):
        before, events = self.rows(), self.events()
        result = self.link_now([self.box_doc(0), self.box_doc(1)])
        self.assertEqual([(item.status, item.message) for item in result.items],
                         [(link_service.NOT_LINKABLE, link_service.NOT_LINKABLE_MESSAGE)] * 2)
        self.assertEqual(result.linked, 0)
        self.link.assert_not_called()
        self.assertEqual((self.rows(), self.events()), (before, events))

    def test_notes_are_not_changed_by_linking(self):
        target = {"inbox_item_id": 1, "path": str(self.inbox_docs[1])}
        notes_service.add_document_note(self.actor, target, "nota previa", request_id=uuid4().hex,
                                        db_path=self.db)
        notes = self.query("SELECT * FROM document_viewer_notes")
        self.link_now([self.doc(1)])
        self.assertEqual(self.query("SELECT * FROM document_viewer_notes"), notes)
        loaded = notes_service.load_document_notes(self.actor, target, db_path=self.db)
        self.assertEqual([note["body"] for note in loaded["notes"]], ["nota previa"])
        self.assertIn("Documento vinculado", [entry["message"] for entry in loaded["activity"]])


class BatchTests(LinkBase):
    def test_each_item_is_prevalidated_and_reported(self):
        documents = [self.doc(1), self.doc(2), self.doc(5), self.doc(99), self.box_doc(), self.doc(4),
                     self.doc(1), self.doc(6)]
        plan = self.prepare(documents)
        self.assertEqual([check.outcome for check in plan.checks], [
            link_service.READY, link_service.READY, link_service.REJECTED, link_service.REJECTED,
            link_service.NOT_LINKABLE, link_service.TRANSFER, link_service.REJECTED,
            link_service.UNCHANGED])
        self.assertEqual(plan.checks[6].message, link_service.REPEATED)
        self.assertEqual((plan.actionable(), plan.actionable(allow_transfer=True)), (2, 3))
        self.link.assert_not_called()  # the review writes nothing
        result = link_service.execute_link(plan, confirmed=True)
        self.assertEqual([item.status for item in result.items], [
            link_service.LINKED, link_service.LINKED, link_service.REJECTED, link_service.REJECTED,
            link_service.NOT_LINKABLE, link_service.REJECTED, link_service.REJECTED,
            link_service.UNCHANGED])
        self.assertEqual(self.link.call_count, 2)
        self.assertEqual((result.linked, result.problems, result.partial), (2, 5, True))
        self.assertFalse(result.atomic)
        self.assertIn("no es atómico", result.policy)
        self.assertEqual(result.summary,
                         "2 vinculado(s) · 1 sin cambios · 1 no vinculable(s) · 4 rechazado(s)")

    def test_a_failure_does_not_undo_previous_links(self):
        def flaky(item_id, **kwargs):
            if item_id == 2:
                raise RuntimeError("disco lleno")
            return self.canonical(item_id, **kwargs)

        self.link.side_effect = flaky
        result = self.link_now([self.doc(1), self.doc(2), self.doc(3)])
        self.assertEqual(self.statuses(result), {1: link_service.LINKED, 2: link_service.FAILED,
                                                 3: link_service.LINKED})
        self.assertEqual(result.items[1].message, link_service.LINK_FAILED)
        self.assertTrue(result.partial)
        # Committed per item: 1 and 3 stay linked, 2 is untouched.
        self.assertEqual([self.row(i)["expedient_id"] for i in (1, 2, 3)], [42, None, 42])
        self.assertEqual(self.row(3)["client_id"], 7)
        self.assertEqual(self.events(2), [])

    def test_canonical_answer_is_checked(self):
        self.link.side_effect = lambda item_id, **kwargs: {"id": item_id, "client_id": 7, "expedient_id": 43}
        result = self.link_now([self.doc(1)])
        self.assertEqual(self.statuses(result), {1: link_service.FAILED})
        self.assertIn("no confirmó", result.items[0].message)

    def test_stale_identity_is_skipped(self):
        plan = self.prepare([self.doc(1), self.doc(2)])
        # Someone else links item 2 between the review and the confirmation.
        self.execute("UPDATE document_inbox_items SET expedient_id = 43, status = 'linked', "
                     "updated_at = '2026-11-09 09:00:00' WHERE id = 2")
        result = link_service.execute_link(plan, confirmed=True)
        self.assertEqual(self.statuses(result), {1: link_service.LINKED, 2: link_service.REJECTED})
        self.assertEqual(result.items[1].message, link_service.STALE)
        self.assertEqual(self.row(2)["expedient_id"], 43)
        self.link.assert_called_once_with(1, client_id=7, expedient_id=42)


class ViewerBase(LinkBase):
    def setUp(self):
        super().setUp()
        self.patch(viewer_service, "PREVIEW_DIR", self.root / "previews")
        exp_root = str((self.root / "box" / "EXP-42").resolve())
        self.patch(viewer_service, "get_expediente_document_root", side_effect=lambda expediente_id: {
            "expediente_id": int(expediente_id), "root_path": exp_root, "exists": True, "message": ""})
        self.page = SimpleNamespace(overlay=[], update=Mock())
        self.on_linked = Mock()

    def linking(self, actor="default"):
        return ViewerLinking(actor=self.actor if actor == "default" else actor,
                             on_linked=self.on_linked, db_path=self.db)

    def notes(self):
        return panel.ViewerNotes(actor=self.actor, db_path=self.db, run=lambda work: work())

    def open_inbox(self, ids, index=0, notes=None, linking="default"):
        queue = [{"path": str(self.inbox_docs[i]), "name": f"Pasaporte {i}.pdf", "key": f"inbox:{i}",
                  "inbox_item_id": i} for i in ids]
        return open_document_viewer_modal(
            self.page, queue[index]["path"], title=queue[index]["name"], queue=queue, queue_index=index,
            near_window=0, notes=notes, linking=self.linking() if linking == "default" else linking)

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def labels(self, dialog):
        return [viewer_action_label(b) for b in viewer_action_buttons(dialog)]

    def links(self, dialog):
        return viewer_layout(dialog).links

    def form(self):
        form = self.page.overlay[-1].data
        self.assertIsInstance(form, link_dialog.LinkForm)
        return form

    @staticmethod
    def pick(select, option_id):
        select.select(next(o for o in select.options if int(o["id"]) == option_id))

    @staticmethod
    def texts(control):
        return [c.value for c in walk(control) if isinstance(c, ft.Text)]

    def confirm(self, form):
        form.confirm.value = True
        form.confirm.on_change(None)

    def check(self, dialog, tile, value):
        checkbox = viewer_layout(dialog).tiles[tile].checkbox
        checkbox.on_change(SimpleNamespace(control=SimpleNamespace(value=value)))

    def note_bodies(self, dialog):
        return [card.content.controls[1].value for card in viewer_layout(dialog).notes.note_cards]


class ViewerLinkTests(ViewerBase):
    def test_link_active_document_keeps_page_zoom_and_document(self):
        dialog = self.open_inbox([1, 2, 3], index=1)
        self.assertIn("Vincular a expediente", self.labels(dialog))
        self.assertNotIn("Vincular seleccionados", self.labels(dialog))
        self.button(dialog, "Zoom +").on_click(None)
        layout = viewer_layout(dialog)
        page_label, zoom_label = layout.page_label.value, layout.zoom_label.value
        self.assertEqual(zoom_label, "Zoom: 2.0x")
        self.assertEqual(self.links(dialog).status_text.value, "Sin expediente")

        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        texts = self.texts(form.dialog)
        self.assertIn(link_dialog.LOGICAL_ONLY, texts)
        self.assertIn("Bandeja #2 · Sin expediente · Cliente #7", texts)
        # The current client is preselected; the expediente is an explicit choice.
        self.assertEqual(form.client_id, 7)
        self.assertIsNone(form.expedient_id)
        self.assertTrue(form.confirm.disabled and form.submit_button.disabled)
        # A second click on the command does not open another form.
        self.button(dialog, "Vincular a expediente").on_click(None)
        self.assertEqual(sum(isinstance(c.data, link_dialog.LinkForm) for c in self.page.overlay), 1)

        self.pick(form.expedient_select, 42)
        self.assertIn(f"Pasaporte {2}.pdf: Se vinculará al expediente {TARGET}.", self.texts(form.dialog))
        self.assertTrue(form.submit_button.disabled)
        self.assertIsNone(form.submit())  # not confirmed: nothing happens
        self.assertEqual(form.status.value, link_service.NOT_CONFIRMED)
        self.link.assert_not_called()
        self.confirm(form)
        self.assertEqual(form.confirm.label,
                         f"Confirmo vincular 1 documento(s) al expediente {TARGET} del cliente #7.")
        self.assertFalse(form.submit_button.disabled)
        form.submit_button.on_click(None)
        form.submit_button.on_click(None)  # double click
        self.link.assert_called_once_with(2, client_id=7, expedient_id=42)
        self.assertEqual(form.status.value, "1 vinculado(s) · 0 sin cambios. Por ana.")
        self.assertEqual(form.status.color, link_dialog.Q_SUCCESS)
        self.assertFalse(form.submit_button.visible)
        self.on_linked.assert_called_once()

        # The info row shows the link; document, page and zoom are unchanged.
        layout = viewer_layout(dialog)
        self.assertEqual(self.links(dialog).status_text.value, f"Vinculado a {TARGET}")
        self.assertEqual((layout.document.index, layout.page_label.value, layout.zoom_label.value),
                         (1, page_label, zoom_label))
        form.cancel_button.on_click(None)
        self.assertNotIn(form.dialog, self.page.overlay)
        # Navigation afterwards keeps the link state per document.
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(self.links(dialog).status_text.value, "Sin expediente")
        self.button(dialog, "Doc anterior").on_click(None)
        self.assertEqual(self.links(dialog).status_text.value, f"Vinculado a {TARGET}")
        self.button(dialog, "Cerrar").on_click(None)

    def test_reentrant_submit_is_ignored(self):
        dialog = self.open_inbox([1, 2])
        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        self.pick(form.expedient_select, 42)
        self.confirm(form)
        inner = []

        def clicked_again(item_id, **kwargs):
            inner.append(form.submit())  # second click while the first is running
            return self.canonical(item_id, **kwargs)

        self.link.side_effect = clicked_again
        self.assertIsNotNone(form.submit())
        self.assertEqual((inner, self.link.call_count), ([None], 1))
        self.button(dialog, "Cerrar").on_click(None)

    def test_cancel_writes_nothing(self):
        before = self.rows()
        dialog = self.open_inbox([1, 2])
        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        self.pick(form.expedient_select, 42)
        self.confirm(form)
        form.cancel_button.on_click(None)
        self.assertTrue(form.closed)
        self.assertIsNone(form.submit())
        self.link.assert_not_called()
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.links(dialog).status_text.value, "Sin expediente")
        # Changing client or expediente drops a previous confirmation.
        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        self.pick(form.expedient_select, 42)
        self.confirm(form)
        self.pick(form.expedient_select, 43)
        self.assertFalse(form.confirm.value)
        self.assertTrue(form.submit_button.disabled)
        self.pick(form.client_select, 8)
        self.assertIsNone(form.plan)
        self.assertTrue(form.submit_button.disabled)
        # Closing the viewer closes the form too.
        self.button(dialog, "Cerrar").on_click(None)
        self.assertTrue(form.closed)
        self.link.assert_not_called()

    def test_errors_are_visible(self):
        dialog = self.open_inbox([1, 2], linking=self.linking(actor=None))
        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        self.assertEqual(form.status.value, link_service.NO_ACTOR)
        self.assertFalse(form.submit_button.visible)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

        dialog = self.open_inbox([1, 2])
        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        self.pick(form.expedient_select, 42)
        self.confirm(form)
        self.execute("UPDATE expedientes SET activo = 0 WHERE id = 42")
        self.assertIsNone(form.submit())
        self.assertIn("archivado", form.status.value)
        self.assertEqual(form.status.color, link_dialog.Q_ERROR)
        self.assertFalse(form.submit_button.disabled)  # can retry after fixing it
        self.link.assert_not_called()
        self.assertEqual(self.links(dialog).status_text.value, "Sin expediente")
        self.button(dialog, "Cerrar").on_click(None)

    def test_compare_multi_selection_is_independent_and_partial(self):
        target = {"inbox_item_id": 2, "path": str(self.inbox_docs[2])}
        notes_service.add_document_note(self.actor, target, "nota del activo", request_id=uuid4().hex,
                                        db_path=self.db)
        notes_rows = self.query("SELECT * FROM document_viewer_notes")
        dialog = self.open_inbox([1, 2, 5, 4, 3], notes=self.notes())
        self.button(dialog, "Comparador 4").on_click(None)
        links = self.links(dialog)
        self.assertEqual(links.counter_text.value, "0 seleccionados")
        self.assertTrue(self.button(dialog, "Vincular seleccionados").disabled)
        self.assertIsNone(links.open_selected())

        for tile in (0, 2, 3):
            self.check(dialog, tile, True)
        # The active document is a separate thing: tile 1 becomes active for page/zoom/notes.
        viewer_layout(dialog).tiles[1].zoom_in.on_click(None)
        viewer_layout(dialog).tiles[1].next_page.on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.document.index, 1)
        self.assertEqual([t.checkbox.value for t in layout.tiles], [True, False, True, True])
        self.assertEqual(links.counter_text.value, "3 seleccionados")
        self.assertEqual(self.note_bodies(dialog), ["nota del activo"])
        tile_state = (layout.tiles[1].page_label.value, layout.tiles[1].zoom_label.value)
        self.assertEqual(tile_state, ("Página 2 de 2", "1.4x"))
        group = layout.group_label.value

        self.button(dialog, "Vincular seleccionados").on_click(None)
        form = self.form()
        self.assertEqual(form.dialog.title.value, "Vincular 3 documentos seleccionados")
        self.assertIn(link_service.BATCH_POLICY, self.texts(form.dialog))
        self.assertEqual([r["inbox_item_id"] for r in form.requests], [1, 5, 4])
        self.pick(form.expedient_select, 42)
        self.assertTrue(form.transfer.visible)
        self.confirm(form)
        self.assertIn("Confirmo vincular 1 documento(s)", form.confirm.label)
        form.submit_button.on_click(None)
        self.assertEqual(self.link.call_count, 1)
        self.assertEqual(form.result.summary, "1 vinculado(s) · 0 sin cambios · 2 rechazado(s)")
        self.assertIn("Resultado parcial: " + link_service.BATCH_POLICY, form.status.value)
        self.assertEqual(form.status.color, link_dialog.Q_WARNING)
        self.assertEqual([(t.value, t.data) for t in form.review_column.controls[1:]], [
            (f"Pasaporte 1.pdf: Vinculado al expediente {TARGET}.", link_service.LINKED),
            ("Pasaporte 5.pdf: Descartado en Bandeja: restáuralo antes de vincularlo.",
             link_service.REJECTED),
            ("Pasaporte 4.pdf: Vinculado al expediente #43: trasladarlo requiere confirmación "
             "especial. No confirmado: no se ha modificado.", link_service.REJECTED),
        ])
        form.close()

        # Viewer state survives: active tile, its page and zoom, group, notes; failed ones stay selected.
        layout = viewer_layout(dialog)
        self.assertEqual(layout.document.index, 1)
        self.assertEqual((layout.tiles[1].page_label.value, layout.tiles[1].zoom_label.value), tile_state)
        self.assertEqual(layout.group_label.value, group)
        self.assertEqual([t.checkbox.value for t in layout.tiles], [False, False, True, True])
        self.assertEqual(links.counter_text.value, "2 seleccionados")
        self.assertEqual(self.note_bodies(dialog), ["nota del activo"])
        self.assertEqual(self.query("SELECT * FROM document_viewer_notes"), notes_rows)
        self.assertEqual([self.row(i)["expedient_id"] for i in (1, 4, 5)], [42, 43, None])

        # The transfer, now with the special confirmation.
        self.button(dialog, "Vincular seleccionados").on_click(None)
        form = self.form()
        self.pick(form.expedient_select, 42)
        form.transfer.value = True
        form.transfer.on_change(None)
        self.confirm(form)
        form.submit_button.on_click(None)
        self.assertEqual(self.statuses(form.result), {5: link_service.REJECTED, 4: link_service.LINKED})
        form.close()
        self.assertEqual(self.row(4)["expedient_id"], 42)
        self.assertEqual(links.counter_text.value, "1 seleccionado")
        # Linked tile shows its new state and its Bandeja activity when it becomes active.
        viewer_layout(dialog).tiles[0].container.on_click(None)
        self.assertEqual(links.status_text.value, f"Vinculado a {TARGET}")
        self.assertIn("Documento vinculado", self.texts(viewer_layout(dialog).notes.container))
        self.button(dialog, "Cerrar").on_click(None)

    def test_box_only_expediente_documents_are_not_linkable(self):
        before, events = self.rows(), self.events()
        queue = [{"path": str(path), "name": path.name} for path in self.exp_docs]
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], expediente_id=42, queue=queue,
                                            near_window=0, linking=self.linking())
        self.assertEqual(self.links(dialog).status_text.value, "No vinculable directamente")
        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        self.assertEqual(form.status.value, link_service.NOT_LINKABLE_MESSAGE)
        self.assertIn(f"Carpeta de expediente · {link_service.NOT_LINKABLE_MESSAGE}", self.texts(form.dialog))
        self.assertFalse(form.submit_button.visible)
        self.assertEqual(viewer_action_label(form.cancel_button), "Cerrar")
        form.cancel_button.on_click(None)
        self.button(dialog, "Comparador 4").on_click(None)
        self.check(dialog, 0, True)
        self.check(dialog, 1, True)
        self.button(dialog, "Vincular seleccionados").on_click(None)
        self.assertEqual(self.form().status.value, link_service.NOT_LINKABLE_MESSAGE)
        self.form().close()
        self.button(dialog, "Cerrar").on_click(None)
        self.link.assert_not_called()
        self.assertEqual((self.rows(), self.events()), (before, events))

    def test_without_linking_the_viewer_is_unchanged(self):
        dialog = self.open_inbox([1, 2], linking=None)
        self.assertIsNone(self.links(dialog))
        self.assertNotIn("Vincular a expediente", self.labels(dialog))
        self.button(dialog, "Comparador 4").on_click(None)
        self.assertTrue(all(t.checkbox is None for t in viewer_layout(dialog).tiles))
        self.button(dialog, "Cerrar").on_click(None)


class WiringAndScopeTests(ViewerBase):
    def test_inbox_view_passes_each_item_to_the_viewer(self):
        items = [document_inbox_service.get_inbox_item(i) for i in (1, 2, 3)]
        state = {"selected_item_id": 2, "selected_item_ids": set(), "items": copy.deepcopy(items),
                 "viewer_linking": self.linking()}
        show_error = Mock()
        scope = bind(INBOX, ("selected_item", "inbox_viewer_options", "show_preview"), dict(
            page=self.page, state=state, open_document_viewer_modal=open_document_viewer_modal,
            document_inbox_service=document_inbox_service, show_error=show_error,
            pdf_toolbar_for_item=lambda item, queue=(): None,
        ))
        scope["show_preview"]()
        show_error.assert_not_called()
        dialog = self.page.overlay[-1]
        links = self.links(dialog)
        self.assertEqual(links.linking.inbox_items, (
            (str(self.inbox_docs[2]), 2, None), (str(self.inbox_docs[1]), 1, None),
            (str(self.inbox_docs[2]), 2, None), (str(self.inbox_docs[3]), 3, None)))
        self.button(dialog, "Vincular a expediente").on_click(None)
        form = self.form()
        self.assertEqual(form.requests[0]["inbox_item_id"], 2)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_expedients_view_passes_the_session_linking(self):
        linking, canonical = self.linking(), Mock()
        scope = bind(EXPEDIENTS, ("show_document_preview",), dict(
            page=self.page, state={"dialog_expediente_id": 42, "viewer_linking": linking},
            show_form_error=Mock(), open_document_viewer_modal=canonical, document_viewer_dialog=None,
        ))
        scope["show_document_preview"](str(self.exp_docs[0]))
        self.assertIs(canonical.call_args.kwargs["linking"], linking)

    def test_views_inject_the_authenticated_user(self):
        for view, name, expected in (
                (EXPEDIENTS, "expedients_view", "ViewerLinking(actor=current_user)"),
                (INBOX, "document_inbox_view", "ViewerLinking(actor=current_user, on_linked=")):
            tree = ast.parse(view.read_text(encoding="utf-8"))
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertIn(expected, ast.unparse(function))

    def test_scope_only_the_canonical_link_writes(self):
        source = SERVICE.read_text(encoding="utf-8")
        used = set(re.findall(r"document_inbox_service\.(\w+)", source))
        self.assertEqual(used, {"get_expedient", "get_inbox_item", "link_inbox_item",
                                "client_autocomplete_options",
                                "expedient_autocomplete_options_for_client"})
        for path in (SERVICE, DIALOG):
            modules = imported_modules(path)
            for forbidden in ("shutil", "sqlite3", "database", "os", "subprocess",
                              "backend.services.box_watch_service"):
                self.assertFalse(any(m == forbidden or m.startswith(forbidden + ".") for m in modules),
                                 (path.name, forbidden))
        dialog_source = DIALOG.read_text(encoding="utf-8")
        # The dialog only talks to the application service.
        self.assertIsNone(re.search(r"document_inbox_service\.\w+\(", dialog_source))
        self.assertIn("backend.services", imported_modules(DIALOG))
        self.assertIn("link_service.execute_link(", dialog_source)
        for text in (source, dialog_source):
            self.assertNotIn("copy_inbox_item_to_expedient_box", text)
            self.assertNotIn("import_box_file_to_inbox", text)


if __name__ == "__main__":
    unittest.main()
