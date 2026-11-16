"""WO-DV30-03: tareas y avisos del Calendario creados desde el visor documental.

Solo PDFs sintéticos y SQLite en un TemporaryDirectory. La base operativa se
redirige a un fichero que nunca debe aparecer; Bandeja y expedientes son
dobles de los servicios existentes y toda mutación de Bandeja/Box falla el
test. Las notificaciones solo se programan (outbox PENDIENTE): no hay
Telegram ni servicios externos.
"""
import ast
import copy
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import calendar_alert_service
from backend.services import calendar_service
from backend.services import document_inbox_service
from backend.services import document_viewer_actions_service as actions_service
from backend.services import document_viewer_notes_service as notes_service
from backend.services import document_viewer_service as viewer_service
from backend.services import scheduled_notification_service
from backend.services import task_service
from database import connection
from frontend.components import document_viewer_actions_panel as panel
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label, viewer_layout,
)
from frontend.components.document_viewer_multidoc import marked_queue
from frontend.components.document_viewer_notes_panel import ViewerNotes


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPEDIENTS = REPO_ROOT / "frontend" / "views" / "expedients_view.py"
INBOX = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"
SOURCES = (
    REPO_ROOT / "frontend" / "components" / "document_viewer_actions_panel.py",
    REPO_ROOT / "backend" / "services" / "document_viewer_actions_service.py",
)

BASE_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);
INSERT INTO users (id, username, password_hash, is_active)
VALUES (1, 'ana', 'x', 1), (3, 'baja', 'x', 0);
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY,
    nombre TEXT,
    primer_apellido TEXT,
    segundo_apellido TEXT
);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER,
    numero_expediente TEXT
);
INSERT INTO clientes VALUES (7, 'ANA', 'GUILHERME', 'BORGES');
INSERT INTO expedientes VALUES (42, 7, 'EXP-2026-0042'), (43, 7, 'EXP-2026-0043');
"""
DEFAULT = object()
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


def future(days=5, hour=10, minute=30):
    return (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=minute, second=0,
                                                           microsecond=0)


class ActionsBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "crm.db"
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(BASE_SQL)
        task_service.ensure_task_schema(db_path=self.db)
        calendar_alert_service.ensure_calendar_alert_schema(db_path=self.db)
        scheduled_notification_service.ensure_schema(db_path=self.db)
        # Anything reaching the operational database would create this file.
        self.operational = self.root / "operational.db"
        self.patch(connection, "DB_PATH", str(self.operational))
        self.actor = {"id": 1, "username": "ana"}

        # Expediente 42 with its Box folder; 43 exists without documents.
        self.exp_root = self.root / "box" / "EXP-42"
        self.exp_docs = [self.exp_root / name for name in
                         ("Contrato.pdf", "Nomina.pdf", "Pasaporte.pdf", "Recibo.pdf", "Padron.pdf")]
        for index, path in enumerate(self.exp_docs):
            make_pdf(path, f"expediente {index}")
        self.patch(viewer_service, "get_expediente_document_root", side_effect=self.expediente_root)
        self.expedients = {42: {"id": 42, "cliente_id": 7, "numero_expediente": "EXP-2026-0042"},
                           43: {"id": 43, "cliente_id": 7, "numero_expediente": "EXP-2026-0043"}}
        self.patch(document_inbox_service, "get_expedient",
                   side_effect=lambda eid: copy.deepcopy(self.expedients.get(int(eid), {})))

        # Bandeja: item 1 without expediente, items 2 and 3 linked to 42.
        self.inbox_docs = [self.root / "inbox" / f"{number}_Escrito.pdf" for number in (1, 2, 3)]
        for index, path in enumerate(self.inbox_docs):
            make_pdf(path, f"bandeja {index}")
        self.items = {index + 1: {
            "id": index + 1, "stored_path": str(path), "original_filename": "Escrito.pdf",
            "status": "pending" if index == 0 else "linked", "client_id": 7,
            "expedient_id": None if index == 0 else 42, "notes": "",
        } for index, path in enumerate(self.inbox_docs)}
        self.patch(document_inbox_service, "get_inbox_item", side_effect=self.get_item)
        self.patch(document_inbox_service, "get_inbox_events", return_value=[])
        for name in INBOX_MUTATIONS:
            self.patch(document_inbox_service, name, side_effect=AssertionError(name))
        self.files = {path: path.read_bytes() for path in self.exp_docs + self.inbox_docs}

    def tearDown(self):
        # Box/PDF files are never altered and the operational DB is never opened.
        for path, data in self.files.items():
            self.assertEqual(path.read_bytes(), data, path)
        self.assertFalse(self.operational.exists())

    def patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def expediente_root(self, expediente_id):
        if int(expediente_id) == 42:
            return {"expediente_id": 42, "root_path": str(self.exp_root.resolve()),
                    "exists": True, "message": ""}
        if int(expediente_id) in self.expedients:
            return {"expediente_id": int(expediente_id), "root_path": "", "exists": False,
                    "message": "El expediente no tiene carpeta Box vinculada."}
        raise ValueError("Expediente no encontrado")

    def get_item(self, item_id):
        item = self.items.get(int(item_id))
        if item is None:
            raise ValueError("No existe el documento de bandeja indicado.")
        return copy.deepcopy(item)

    def exp(self, index):
        return {"expediente_id": 42, "path": str(self.exp_docs[index])}

    def inbox(self, item_id):
        return {"inbox_item_id": item_id, "path": str(self.inbox_docs[item_id - 1])}

    def rows(self, table):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]

    def counts(self):
        return {table: len(self.rows(table))
                for table in ("tasks", "calendar_alerts", "scheduled_notifications")}

    def task(self, target, request_id="req-task-000001", **values):
        values.setdefault("titulo", "Presentar recurso")
        values.setdefault("fecha_vencimiento", future().strftime("%d/%m/%Y %H:%M"))
        return actions_service.create_task(self.actor, target, request_id=request_id,
                                           db_path=self.db, **values)

    def alert(self, target, request_id="req-alert-00001", **values):
        values.setdefault("titulo", "Cita en extranjería")
        values.setdefault("fecha_evento", future(days=8).strftime("%d/%m/%Y %H:%M"))
        return actions_service.create_alert(self.actor, target, request_id=request_id,
                                            db_path=self.db, **values)

    def assert_nothing_written(self):
        self.assertEqual(self.counts(), {"tasks": 0, "calendar_alerts": 0,
                                         "scheduled_notifications": 0})


# ---------------------------------------------------------------------- service


class TaskAndAlertServiceTests(ActionsBase):
    def test_task_is_a_canonical_task_of_the_document_and_its_expediente(self):
        due = future(hour=9, minute=15)
        result = self.task(self.exp(0), titulo="  Presentar recurso  ", descripcion="Plazo de alzada",
                           fecha_vencimiento=due.strftime("%d/%m/%Y %H:%M"), prioridad="alta",
                           responsable="Luis")
        self.assertTrue(result["created"])
        [task] = self.rows("tasks")
        ref = notes_service.resolve_identity(self.exp(0)).ref
        self.assertEqual((task["origen_tipo"], task["origen_id"]), ("DOCUMENTO", ref))
        self.assertEqual((task["expediente_id"], task["cliente_id"]), (42, 7))
        self.assertEqual((task["titulo"], task["prioridad"], task["responsable"]),
                         ("Presentar recurso", "ALTA", "Luis"))
        self.assertEqual(task["fecha_vencimiento"], due.isoformat(sep=" "))
        self.assertEqual(task["estado"], "PENDIENTE")
        self.assertEqual(task["created_by"], "ana")
        self.assertEqual(task["source_key"], "DOCVIEWER:TASK:req-task-000001")
        self.assertTrue(task["descripcion"].startswith("Plazo de alzada\n\nOrigen: visor documental"))
        self.assertIn("Contrato.pdf", task["descripcion"])
        self.assertIn("EXP-2026-0042 (#42)", task["descripcion"])
        # Planning in the same transaction: ALTA -> 24 h before and at due time, pending only.
        notifications = self.rows("scheduled_notifications")
        self.assertEqual({n["source_type"] for n in notifications}, {"TASK"})
        self.assertEqual({n["source_id"] for n in notifications}, {task["id"]})
        self.assertEqual({n["estado"] for n in notifications}, {"PENDIENTE"})
        self.assertEqual(len(notifications), 2)
        self.assertEqual(self.rows("calendar_alerts"), [])

    def test_alert_of_a_linked_inbox_item_uses_the_item_expediente(self):
        event, warning = future(days=8, hour=12, minute=0), future(days=7, hour=9, minute=0)
        result = self.alert(self.inbox(2), fecha_evento=event.strftime("%Y-%m-%d %H:%M"),
                            fecha_inicio_aviso=warning.strftime("%d/%m/%Y %H:%M"), prioridad="URGENTE")
        self.assertTrue(result["created"])
        [alert] = self.rows("calendar_alerts")
        self.assertEqual((alert["origen_tipo"], alert["origen_id"]), ("DOCUMENTO", "inbox:2"))
        self.assertEqual((alert["expediente_id"], alert["cliente_id"]), (42, 7))
        self.assertIsNone(alert["documento_id"])
        self.assertEqual(alert["fecha_evento"], event.isoformat(sep=" "))
        self.assertEqual(alert["fecha_inicio_aviso"], warning.isoformat(sep=" "))
        self.assertEqual(alert["estado"], "ACTIVO")
        self.assertIn("Bandeja #2", alert["descripcion"])
        [notification] = self.rows("scheduled_notifications")
        self.assertEqual((notification["source_type"], notification["source_id"]), ("ALERT", alert["id"]))
        self.assertEqual(notification["estado"], "PENDIENTE")
        self.assertEqual(notification["scheduled_at"], warning.isoformat(sep=" "))
        self.assertEqual(self.rows("tasks"), [])

    def test_task_and_alert_appear_in_the_canonical_calendar(self):
        task = self.task(self.exp(1))["task"]
        alert = self.alert(self.inbox(3))["alert"]
        items = calendar_service.list_calendar_items(db_path=self.db)
        found = {(item["item_type"], item["source_id"]): item for item in items}
        self.assertEqual(set(found), {("TASK", task["id"]), ("ALERT", alert["id"])})
        self.assertEqual(found[("TASK", task["id"])]["origin_type"], "DOCUMENTO")
        self.assertEqual(found[("ALERT", alert["id"])]["origin_id"], "inbox:3")
        self.assertEqual([t["id"] for t in task_service.list_tasks(expediente_id=42, db_path=self.db)],
                         [task["id"]])
        self.assertEqual([a["id"] for a in calendar_alert_service.list_alerts(expediente_id=42,
                                                                               db_path=self.db)],
                         [alert["id"]])

    def test_unlinked_inbox_item_is_never_assigned_an_expediente(self):
        for create in (self.task, self.alert):
            with self.subTest(create.__name__):
                with self.assertRaisesRegex(actions_service.DocumentActionError,
                                            "Vincula primero el documento a un expediente"):
                    create(self.inbox(1))
                # A forged expediente in the request is ignored: the item decides.
                with self.assertRaisesRegex(actions_service.DocumentActionError, "Vincula primero"):
                    create({**self.inbox(1), "expediente_id": 42})
        self.assert_nothing_written()

    def test_expediente_and_document_are_verified_not_taken_from_the_ui(self):
        outside = self.root / "outside" / "Contrato.pdf"
        make_pdf(outside, "fuera")
        self.files[outside] = outside.read_bytes()
        cases = {
            "file outside the expediente folder": {"expediente_id": 42, "path": str(outside)},
            "file of another expediente's request": {"expediente_id": 43, "path": str(self.exp_docs[0])},
            "unknown expediente": {"expediente_id": 99, "path": str(self.exp_docs[0])},
            "inbox foreign file": {"inbox_item_id": 2, "path": str(self.inbox_docs[2])},
            "inbox missing item": {"inbox_item_id": 99, "path": str(self.inbox_docs[0])},
            "no identity": {"path": str(self.exp_docs[0])},
        }
        for name, target in cases.items():
            with self.subTest(name):
                with self.assertRaises(actions_service.DocumentActionError):
                    self.task(target)
        # The item's expediente no longer exists.
        del self.expedients[42]
        with self.assertRaisesRegex(actions_service.DocumentActionError, actions_service.NO_EXPEDIENT):
            self.alert(self.inbox(2))
        self.assert_nothing_written()

    def test_expediente_changed_since_the_form_was_opened(self):
        context = actions_service.resolve_context(self.actor, self.inbox(2), db_path=self.db)
        self.assertEqual(context.expediente_id, 42)
        self.items[2]["expedient_id"] = 43
        with self.assertRaisesRegex(actions_service.DocumentActionError, "ya no está vinculado"):
            self.task(self.inbox(2), expected_expediente_id=context.expediente_id)
        self.assert_nothing_written()
        result = self.task(self.inbox(2), expected_expediente_id=43)
        self.assertEqual(result["task"]["expediente_id"], 43)

    def test_backend_validation_rejects_without_writes(self):
        past = (datetime.now() - timedelta(days=1)).strftime("%d/%m/%Y %H:%M")
        event = future(days=3)
        task_cases = {
            "empty title": dict(titulo="   "),
            "control characters": dict(titulo="Hola\x07"),
            "long title": dict(titulo="x" * (actions_service.MAX_TITLE + 1)),
            "no due date": dict(fecha_vencimiento=""),
            "date without time": dict(fecha_vencimiento=future().strftime("%d/%m/%Y")),
            "invalid date": dict(fecha_vencimiento="31/02/2027 10:00"),
            "past due date": dict(fecha_vencimiento=past),
            "invalid priority": dict(prioridad="CRITICA"),
            "long responsible": dict(responsable="r" * (actions_service.MAX_RESPONSIBLE + 1)),
            "non text description": dict(descripcion=123),
        }
        for name, values in task_cases.items():
            with self.subTest(name):
                with self.assertRaises(actions_service.DocumentActionError):
                    self.task(self.exp(0), **values)
        alert_cases = {
            "warning after event": dict(fecha_evento=event.strftime("%d/%m/%Y %H:%M"),
                                        fecha_inicio_aviso=(event + timedelta(hours=1)).strftime(
                                            "%d/%m/%Y %H:%M")),
            "past warning": dict(fecha_inicio_aviso=past),
            "past event": dict(fecha_evento=past),
        }
        for name, values in alert_cases.items():
            with self.subTest(name):
                with self.assertRaises(actions_service.DocumentActionError):
                    self.alert(self.exp(0), **values)
        for request_id in ("", "corto", "con espacios 123", None):
            with self.subTest(request_id=request_id):
                with self.assertRaisesRegex(actions_service.DocumentActionError, "Solicitud no válida"):
                    self.task(self.exp(0), request_id=request_id)
        self.assert_nothing_written()

    def test_only_active_session_users(self):
        for actor in (None, {}, {"id": 99, "username": "fantasma"}, {"id": 3, "username": "baja"},
                      {"id": 1, "username": "otro"}):
            with self.subTest(actor=actor):
                with self.assertRaises(actions_service.DocumentActionError):
                    actions_service.create_task(actor, self.exp(0), titulo="x", request_id="req-actor-0001",
                                                fecha_vencimiento=future(), db_path=self.db)
        self.assert_nothing_written()

    def test_planning_failure_rolls_back_the_task_and_the_alert(self):
        with patch.object(scheduled_notification_service, "schedule_task_notifications",
                          side_effect=RuntimeError("outbox caída")):
            with self.assertRaisesRegex(actions_service.DocumentActionError, "no se ha guardado nada"):
                self.task(self.exp(0))
        with patch.object(scheduled_notification_service, "schedule_alert_notification",
                          side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaisesRegex(actions_service.DocumentActionError, "no se ha guardado nada"):
                self.alert(self.exp(0))
        self.assert_nothing_written()
        # The same request succeeds once planning works again.
        self.assertTrue(self.task(self.exp(0))["created"])
        self.assertEqual(len(self.rows("tasks")), 1)

    def test_repeated_source_key_returns_the_same_record_and_new_requests_create_others(self):
        first = self.task(self.exp(0), request_id="req-repeat-0001")
        again = self.task(self.exp(0), request_id="req-repeat-0001")
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(first["task"]["id"], again["task"]["id"])
        self.assertEqual(again["notifications"], [])
        self.assertEqual(len(self.rows("tasks")), 1)
        planned = len(self.rows("scheduled_notifications"))
        later = self.task(self.exp(0), request_id="req-repeat-0002")
        self.assertTrue(later["created"])
        self.assertEqual(len(self.rows("tasks")), 2)
        self.assertGreater(len(self.rows("scheduled_notifications")), planned)
        # A request id of another document never returns that document's task.
        with self.assertRaisesRegex(actions_service.DocumentActionError, "ya se usó"):
            self.task(self.exp(1), request_id="req-repeat-0001")
        alert = self.alert(self.exp(0), request_id="req-repeat-0001")
        self.assertTrue(alert["created"])  # alerts have their own namespace
        self.assertEqual(self.alert(self.exp(0), request_id="req-repeat-0001")["alert"]["id"],
                         alert["alert"]["id"])
        self.assertEqual(len(self.rows("calendar_alerts")), 1)

    def test_no_absolute_paths_in_stored_records(self):
        self.task(self.exp(2), descripcion="Revisar")
        self.alert(self.inbox(2))
        for row in self.rows("tasks") + self.rows("calendar_alerts"):
            for value in row.values():
                self.assertNotIn(str(self.root), str(value or ""))

    def test_sources_have_no_sql_ddl_or_direct_sending(self):
        for source in SOURCES:
            text = source.read_text(encoding="utf-8")
            tree = ast.parse(text)
            modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                       for alias in node.names}
            modules |= {node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module}
            self.assertFalse({m for m in modules if m == "sqlite3" or m.startswith("database")}, source)
            self.assertFalse({m for m in modules if "telegram" in m}, source)
            upper = text.upper()
            for keyword in ("SELECT ", "INSERT ", "UPDATE ", "CREATE TABLE", "ALTER TABLE"):
                self.assertNotIn(keyword, upper, (source, keyword))
            self.assertNotIn("full_screen", text)


# ---------------------------------------------------------------------- viewer


class ViewerBase(ActionsBase):
    def setUp(self):
        super().setUp()
        self.patch(viewer_service, "PREVIEW_DIR", self.root / "previews")
        self.page = SimpleNamespace(overlay=[], update=Mock())

    def actions(self, run=None, **kwargs):
        kwargs.setdefault("actor", self.actor)
        return panel.ViewerActions(db_path=self.db, run=run or (lambda work: work()), **kwargs)

    def notes(self):
        return ViewerNotes(actor=self.actor, db_path=self.db, run=lambda work: work())

    def open_expedient(self, index=0, actions=DEFAULT, notes=None):
        queue = [{"path": str(path), "name": path.name} for path in self.exp_docs]
        return open_document_viewer_modal(
            self.page, queue[index]["path"], title=queue[index]["name"], expediente_id=42,
            queue=queue, queue_index=index, near_window=0,
            actions=self.actions() if actions is DEFAULT else actions, notes=notes)

    def in_overlay(self, control):
        return any(entry is control for entry in self.page.overlay)

    def open_inbox(self, index=0, actions=None):
        queue = [{"path": str(path), "name": "Escrito.pdf", "key": f"inbox:{n}", "inbox_item_id": n}
                 for n, path in enumerate(self.inbox_docs, start=1)]
        actions = (actions or self.actions()).with_inbox_items(
            [(entry["path"], entry["inbox_item_id"]) for entry in queue])
        return open_document_viewer_modal(self.page, queue[index]["path"], queue=queue,
                                          queue_index=index, near_window=0, actions=actions)

    @staticmethod
    def run_jobs(jobs):
        while jobs:
            jobs.pop(0)()

    def controller(self, dialog):
        return viewer_layout(dialog).actions

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def compare(self, dialog):
        self.button(dialog, "Comparador 4").on_click(None)
        return viewer_layout(dialog)

    def open_form(self, dialog, kind=panel.TASK):
        controller = self.controller(dialog)
        button = controller.task_button if kind == panel.TASK else controller.alert_button
        button.on_click(None)
        form = controller.form
        self.assertIsInstance(form, panel.ActionForm)
        self.assertIs(self.page.overlay[-1], form.dialog)
        return form

    @staticmethod
    def fill(form, title="Revisar documento", moment=None, **extra):
        moment = moment or future()
        form.title_field.value = title
        form.date_field.value = moment.strftime("%d/%m/%Y")
        form.time_field.value = moment.strftime("%H:%M")
        for name, value in extra.items():
            getattr(form, name).value = value

    @staticmethod
    def texts(control):
        return [c.value for c in walk(control) if isinstance(c, ft.Text)]


class ViewerActionsTests(ViewerBase):
    def test_header_commands_follow_the_active_document_without_changing_the_toolbar(self):
        plain = self.open_expedient(actions=None)
        expected = [viewer_action_label(b) for b in viewer_action_buttons(plain)]
        self.assertIsNone(viewer_layout(plain).actions)
        self.button(plain, "Cerrar").on_click(None)

        # Without ``actions`` the DV23 header is unchanged.
        dialog = open_document_viewer_modal(self.page, str(self.exp_docs[0]), expediente_id=42,
                                            near_window=0)
        self.assertNotIn(panel.TASK_LABEL, [viewer_action_label(c) for c in walk(dialog.title)])
        self.button(dialog, "Cerrar").on_click(None)

        dialog = self.open_expedient()
        controller = self.controller(dialog)
        labels = [viewer_action_label(c) for c in walk(dialog.title) if isinstance(c, ft.OutlinedButton)]
        self.assertEqual(labels, [panel.TASK_LABEL, panel.ALERT_LABEL])
        self.assertTrue(any(c is controller.row for c in walk(dialog.title)))
        self.assertFalse(controller.task_button.disabled)
        self.assertFalse(controller.alert_button.disabled)
        self.assertIn("EXP-2026-0042 (#42)", controller.task_button.tooltip)
        # The historical toolbar order is untouched.
        self.assertEqual([viewer_action_label(b) for b in viewer_action_buttons(dialog)], expected)
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(controller.document.index, 1)
        self.assertTrue(any(c is controller.task_button for c in walk(dialog.title)))
        layout = self.compare(dialog)
        layout.tiles[2].container.on_click(None)
        self.assertEqual(controller.document.index, 2)
        self.assertTrue(any(c is controller.alert_button for c in walk(dialog.title)))
        self.assertFalse(controller.alert_button.disabled)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertTrue(controller.closed)

    def test_opening_navigating_and_saving_notes_create_nothing(self):
        dialog = self.open_expedient(notes=self.notes())
        self.button(dialog, "Doc siguiente").on_click(None)
        self.button(dialog, "Zoom +").on_click(None)
        layout = self.compare(dialog)
        layout.tiles[3].container.on_click(None)
        self.button(dialog, "Documento único").on_click(None)
        notes = viewer_layout(dialog).notes
        notes.field.value = "Nota sin tarea"
        notes.field.on_change(SimpleNamespace(control=notes.field))
        notes.send_button.on_click(None)
        self.assertEqual(notes.feedback_text.value, "Nota añadida.")
        # Opening and cancelling a form writes nothing either.
        self.open_form(dialog).cancel_button.on_click(None)
        self.open_form(dialog, panel.ALERT).cancel_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)
        self.assert_nothing_written()

    def test_task_form_creates_a_calendar_task_and_keeps_the_viewer(self):
        dialog = self.open_expedient(1, notes=self.notes())
        self.button(dialog, "Zoom +").on_click(None)
        notes = viewer_layout(dialog).notes
        notes.field.value = "borrador sin enviar"
        notes.field.on_change(SimpleNamespace(control=notes.field))
        before = (viewer_layout(dialog), viewer_layout(dialog).zoom_label.value, dialog.content)

        form = self.open_form(dialog)
        texts = self.texts(form.dialog.content)
        self.assertIn("Documento: Nomina.pdf", texts)
        self.assertIn("Nomina.pdf · Expediente EXP-2026-0042 (#42)", texts)
        # Document and expediente are shown, never editable fields.
        self.assertFalse([c for c in walk(form.dialog.content)
                          if isinstance(c, ft.TextField) and "xpediente" in str(c.label)])
        self.assertEqual(form.priority_field.value, "NORMAL")
        due = future(days=4, hour=11, minute=45)
        self.fill(form, "Pedir nómina firmada", due, responsible_field="Luis",
                  description_field="Falta la firma")
        form.priority_field.value = "URGENTE"
        form.save_button.on_click(None)
        [task] = self.rows("tasks")
        self.assertEqual(form.status.value,
                         f"Tarea #{task['id']} creada en el Calendario · vence {due:%d/%m/%Y %H:%M}.")
        self.assertFalse(form.save_button.visible)
        self.assertEqual(viewer_action_label(form.cancel_button), "Cerrar")
        self.assertEqual((task["titulo"], task["prioridad"], task["responsable"]),
                         ("Pedir nómina firmada", "URGENTE", "Luis"))
        self.assertEqual(task["origen_id"], notes_service.resolve_identity(self.exp(1)).ref)
        self.assertEqual(task["expediente_id"], 42)
        form.cancel_button.on_click(None)
        self.assertTrue(form.closed)
        self.assertFalse(self.in_overlay(form.dialog))
        # The viewer was never re-rendered: same shell, zoom and notes draft.
        self.assertIs(viewer_layout(dialog), before[0])
        self.assertIs(dialog.content, before[2])
        self.assertEqual(viewer_layout(dialog).zoom_label.value, before[1])
        self.assertEqual((notes.field.value, notes.state.draft), ("borrador sin enviar",) * 2)
        self.assertTrue(dialog.open)
        self.assertTrue(self.in_overlay(dialog))
        self.button(dialog, "Cerrar").on_click(None)

    def test_alert_form_creates_a_calendar_alert(self):
        dialog = self.open_expedient(2)
        form = self.open_form(dialog, panel.ALERT)
        event, warning = future(days=9, hour=10, minute=0), future(days=8, hour=9, minute=0)
        self.fill(form, "Cita de huellas", event, warning_date_field=warning.strftime("%d/%m/%Y"),
                  warning_time_field=warning.strftime("%H:%M"))
        form.save_button.on_click(None)
        [alert] = self.rows("calendar_alerts")
        self.assertEqual(form.status.value,
                         f"Aviso #{alert['id']} creado en el Calendario · {event:%d/%m/%Y %H:%M}.")
        self.assertEqual(alert["fecha_inicio_aviso"], warning.isoformat(sep=" "))
        self.assertEqual(alert["origen_tipo"], "DOCUMENTO")
        self.assertEqual(self.rows("tasks"), [])
        [notification] = self.rows("scheduled_notifications")
        self.assertEqual(notification["source_type"], "ALERT")
        form.cancel_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)

    def test_validation_and_planning_errors_are_visible_and_actionable(self):
        dialog = self.open_expedient()
        form = self.open_form(dialog)
        self.fill(form, title="   ")
        form.save_button.on_click(None)
        self.assertEqual(form.status.value, "El título es obligatorio.")
        self.assertFalse(form.save_button.disabled)
        self.assertFalse(form.title_field.disabled)
        form.time_field.value = "25:99"
        form.title_field.value = "Válida"
        form.save_button.on_click(None)
        self.assertIn("no es válida", form.status.value)
        self.fill(form, "Válida")
        with patch.object(scheduled_notification_service, "schedule_task_notifications",
                          side_effect=RuntimeError("outbox")):
            form.save_button.on_click(None)
        self.assertEqual(form.status.value, actions_service.TASK_FAILED)
        self.assertEqual(viewer_action_label(form.save_button), "Guardar")
        self.assert_nothing_written()
        form.save_button.on_click(None)
        self.assertEqual(len(self.rows("tasks")), 1)
        form.cancel_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)

    def test_double_click_and_retry_reuse_the_source_key(self):
        jobs = []
        dialog = self.open_expedient(actions=self.actions(run=jobs.append))
        self.run_jobs(jobs)  # the verification of the active document
        form = self.open_form(dialog)
        self.fill(form, "Doble clic")
        save = form.save_button
        save.on_click(None)
        save.on_click(None)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(form.save_button.disabled)
        self.assertEqual(viewer_action_label(form.save_button), "Guardando…")
        self.run_jobs(jobs)
        self.assertEqual(len(self.rows("tasks")), 1)
        form.cancel_button.on_click(None)

        # The first attempt commits but reports an error; the retry reuses its key.
        real, request_ids = actions_service.create_task, []

        def flaky(*args, **kwargs):
            result = real(*args, **kwargs)
            request_ids.append(kwargs["request_id"])
            if len(request_ids) == 1:
                raise actions_service.DocumentActionError("Conexión interrumpida.")
            return result

        form = self.open_form(dialog)
        self.fill(form, "Reintento")
        with patch.object(actions_service, "create_task", side_effect=flaky):
            form.save_button.on_click(None)
            self.run_jobs(jobs)
            self.assertEqual(form.status.value, "Conexión interrumpida.")
            form.save_button.on_click(None)
            self.run_jobs(jobs)
        self.assertEqual(request_ids[0], request_ids[1])
        self.assertIn("Ya estaba guardado: no se ha duplicado.", form.status.value)
        self.assertEqual([t["titulo"] for t in self.rows("tasks")], ["Doble clic", "Reintento"])
        form.cancel_button.on_click(None)

        # A later form is a new submission with another key.
        form = self.open_form(dialog)
        self.fill(form, "Reintento")
        form.save_button.on_click(None)
        self.run_jobs(jobs)
        keys = [t["source_key"] for t in self.rows("tasks")]
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 3)
        form.cancel_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)

    def test_one_form_at_a_time(self):
        dialog = self.open_expedient()
        form = self.open_form(dialog)
        controller = self.controller(dialog)
        self.assertIsNone(controller.open(panel.ALERT))
        self.assertIs(controller.form, form)
        self.assertEqual(sum(isinstance(getattr(d, "data", None), panel.ActionForm)
                             for d in self.page.overlay), 1)
        form.cancel_button.on_click(None)
        self.assertIsInstance(controller.open(panel.ALERT), panel.ActionForm)
        self.button(dialog, "Cerrar").on_click(None)

    def test_comparator_uses_the_active_document(self):
        dialog = self.open_expedient()
        layout = self.compare(dialog)
        layout.tiles[3].container.on_click(None)
        self.assertEqual(viewer_layout(dialog).document.index, 3)
        form = self.open_form(dialog)
        self.assertEqual(form.target["path"], str(self.exp_docs[3]))
        self.assertEqual(form.context.document_name, "Recibo.pdf")
        self.fill(form, "Del activo")
        form.save_button.on_click(None)
        [task] = self.rows("tasks")
        self.assertEqual(task["origen_id"], notes_service.resolve_identity(self.exp(3)).ref)
        form.cancel_button.on_click(None)
        # Another tile becomes active: the next form follows it.
        viewer_layout(dialog).tiles[1].container.on_click(None)
        form = self.open_form(dialog, panel.ALERT)
        self.assertEqual(form.context.document_name, "Nomina.pdf")
        form.cancel_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)

    def test_changing_document_while_checking_never_mixes_states(self):
        jobs = []
        dialog = self.open_expedient(actions=self.actions(run=jobs.append))
        controller = self.controller(dialog)
        self.assertTrue(controller.task_button.disabled)
        self.assertEqual(controller.task_button.tooltip, panel.CHECKING_HINT)
        self.assertIsNone(controller.open(panel.TASK))
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(len(jobs), 2)
        jobs.pop(0)()  # the first document's check lands after the switch
        self.assertTrue(controller.task_button.disabled)
        jobs.pop(0)()
        self.assertFalse(controller.task_button.disabled)
        self.assertEqual(self.open_form(dialog).context.document_name, "Nomina.pdf")
        controller.form.cancel_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)

    def test_inbox_unlinked_item_is_disabled_and_linked_item_enabled(self):
        dialog = self.open_inbox(0)
        controller = self.controller(dialog)
        for button in controller.buttons:
            self.assertTrue(button.disabled)
            self.assertIsNone(button.on_click)
            self.assertEqual(button.tooltip, actions_service.NOT_LINKED)
        self.assertIsNone(controller.open(panel.TASK))
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertFalse(controller.task_button.disabled)
        form = self.open_form(dialog)
        self.assertEqual(form.context.expediente_id, 42)
        self.assertEqual(form.context.document_label, "Bandeja #2")
        self.fill(form, "Desde Bandeja")
        form.save_button.on_click(None)
        [task] = self.rows("tasks")
        self.assertEqual((task["origen_id"], task["expediente_id"]), ("inbox:2", 42))
        form.cancel_button.on_click(None)
        # Linked from the viewer: the item is verified again and its actions enabled.
        self.button(dialog, "Doc anterior").on_click(None)
        self.assertTrue(controller.task_button.disabled)
        self.items[1]["expedient_id"] = 43
        self.assertTrue(controller.refresh([viewer_layout(dialog).document]))
        self.assertFalse(controller.task_button.disabled)
        self.assertIn("EXP-2026-0043", controller.task_button.tooltip)
        self.button(dialog, "Cerrar").on_click(None)

    def test_inbox_item_relinked_while_the_form_is_open(self):
        dialog = self.open_inbox(1)
        form = self.open_form(dialog)
        self.items[2]["expedient_id"] = None
        self.fill(form, "Ya no vinculado")
        form.save_button.on_click(None)
        self.assertEqual(form.status.value, actions_service.NOT_LINKED)
        self.items[2]["expedient_id"] = 43
        form.save_button.on_click(None)
        self.assertEqual(form.status.value, actions_service.CONTEXT_CHANGED)
        self.assert_nothing_written()
        form.cancel_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)

    def test_closing_the_viewer_during_a_save_keeps_the_record_and_no_ui(self):
        jobs = []
        dialog = self.open_expedient(actions=self.actions(run=jobs.append))
        self.run_jobs(jobs)
        form = self.open_form(dialog)
        self.fill(form, "Guardado tardío")
        form.save_button.on_click(None)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertTrue(form.closed)
        self.assertFalse(self.in_overlay(form.dialog))
        self.assertIsNone(dialog.content)
        flushes, status = self.page.update.call_count, form.status.value
        self.run_jobs(jobs)
        self.assertEqual(len(self.rows("tasks")), 1)  # backend integrity
        self.assertEqual(self.page.update.call_count, flushes)
        self.assertEqual(form.status.value, status)
        self.assertIsNone(dialog.content)
        self.assertFalse(self.in_overlay(form.dialog))


class ViewWiringTests(ViewerBase):
    def test_expedients_view_passes_the_session_actions(self):
        actions, canonical = self.actions(), Mock()
        scope = bind(EXPEDIENTS, ("show_document_preview",), dict(
            page=self.page, state={"dialog_expediente_id": 42, "viewer_actions": actions},
            show_form_error=Mock(), open_document_viewer_modal=canonical, document_viewer_dialog=None,
        ))
        scope["show_document_preview"](str(self.exp_docs[0]))
        self.assertIs(canonical.call_args.kwargs["actions"], actions)
        self.assertEqual(canonical.call_args.kwargs["expediente_id"], 42)

    def test_inbox_view_resolves_each_document_by_its_item(self):
        state = {"selected_item_id": 1, "selected_item_ids": {1, 2},
                 "items": [copy.deepcopy(item) for item in self.items.values()],
                 "viewer_actions": self.actions()}
        show_error = Mock()
        scope = bind(INBOX, ("selected_item", "marked_inbox_items", "inbox_viewer_options",
                             "show_selected_preview"), dict(
            page=self.page, state=state, open_document_viewer_modal=open_document_viewer_modal,
            document_inbox_service=document_inbox_service, show_error=show_error,
            pdf_toolbar_for_item=lambda item, queue=(): None, marked_queue=marked_queue,
        ))
        scope["show_selected_preview"]()
        dialog = self.page.overlay[-1]
        controller = self.controller(dialog)
        self.assertTrue(controller.task_button.disabled)
        self.assertEqual(controller.task_button.tooltip, actions_service.NOT_LINKED)
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertFalse(controller.task_button.disabled)
        self.button(dialog, "Cerrar").on_click(None)
        show_error.assert_not_called()
        self.assert_nothing_written()

    def test_views_inject_the_authenticated_user(self):
        for view, name in ((EXPEDIENTS, "expedients_view"), (INBOX, "document_inbox_view")):
            tree = ast.parse(view.read_text(encoding="utf-8"))
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertIn("ViewerActions(actor=current_user)", ast.unparse(function))


if __name__ == "__main__":
    unittest.main()
