"""WO-DV25-P3B2: archive a copy in Box from the document viewer (P3B2-FIX-ARQ-A).

Builds on the P3A fixtures (``FilingBase``, on top of DV24's ``ViewerBase``): synthetic PDFs,
a synthetic SQLite CRM in a TemporaryDirectory with ``connection.DB_PATH`` redirected to it,
a synthetic classification catalog and a synthetic Box tree. On top of that this suite:

- redirects Bandeja's ``INBOX_ROOT`` to the sandbox and records the real SHA-256 of each item;
- wraps every connection helper so that only the sandbox database can be opened, and checks
  that the habitual ``quesada.db`` is untouched;
- runs the certified P3B1 copy (``copy_inbox_item_to_expedient_box``) FOR REAL, spied: DV24
  patches it to fail, here it is the backend under test. Its answers are only simulated where a
  scenario cannot be produced otherwise (a refusal, a concurrent registration);
- opens the service gate (``EXECUTION_ENABLED``) inside the sandbox only; ``GateTests`` prove it
  is closed in the code and that nothing is written while it is closed;
- DV28-CIERRE: the viewer calls Bandeja's engine directly, like Bandeja does; the DV27 permission
  contract and persistent request store are no longer part of the viewer's path, so the sandbox
  neither installs a contract nor migrates the temporary database (test_dv28_viewer_reuse).

FilingBase's tearDown compares the whole Box tree byte for byte, so every test that copies
declares exactly what appeared (``assert_added``); ``guard()`` makes any mkdir, rename, remove,
shutil copy or Path write fail while the copy runs. No real Box or CRM data is ever reached.
"""
import ast
import copy
import hashlib
import os
import re
import threading
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.services import document_inbox_service
from backend.services import document_viewer_box_archive_service as archive
from backend.services import document_viewer_filing_plan_service as filing
from backend.services import document_viewer_link_service as link_service
from database import connection
from frontend.components import document_viewer_archive_dialog as archive_dialog
from frontend.components import document_viewer_link_dialog as link_dialog
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_label, viewer_layout,
)
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_filing_plan as p3a


SERVICE = dv24.REPO_ROOT / "backend" / "services" / "document_viewer_box_archive_service.py"
ARCHIVE_DIALOG = dv24.REPO_ROOT / "frontend" / "components" / "document_viewer_archive_dialog.py"
REAL_DB = Path(connection.__file__).resolve().with_name("quesada.db")
# The certified P3B1 copy, captured before any test patches it.
REAL_COPY = document_inbox_service.copy_inbox_item_to_expedient_box
K = p3a.KEYS_42
COPY_NAMES = ("copy_inbox_item_to_expedient_box", "copy_document_inbox_batch_to_expedient_box")
GATE_ENV = "QUESADA_VIEWER_BOX_COPY_ENABLED"


def without_gate_env():
    """os.environ without the DV28 gate variable, whatever the shell running the tests has set."""
    return {key: value for key, value in os.environ.items() if key != GATE_ENV}


class ArchiveBase(p3a.FilingBase):
    def setUp(self):
        super().setUp()
        self.real_db_before = self.real_db_state()
        self.db_violations = []
        real_get, real_readonly = connection.get_connection, connection.get_readonly_connection

        def checked_get():
            if Path(connection.DB_PATH).resolve() != self.db.resolve():
                self.db_violations.append(str(connection.DB_PATH))
                raise AssertionError(f"get_connection outside the sandbox: {connection.DB_PATH}")
            return real_get()

        def checked_readonly(db_path=None, timeout=30):
            target = Path(connection.DB_PATH if db_path is None else db_path).resolve()
            if target != self.db.resolve():
                self.db_violations.append(str(target))
                raise AssertionError(f"read-only connection outside the sandbox: {target}")
            return real_readonly(db_path, timeout)

        self.patch(connection, "get_connection", checked_get)
        self.patch(document_inbox_service, "get_connection", checked_get)
        self.patch(connection, "get_readonly_connection", checked_readonly)
        # Bandeja's internal root is the synthetic one; items carry their real SHA-256.
        self.patch(document_inbox_service, "INBOX_ROOT", self.root / "inbox")
        for item_id, path in self.inbox_docs.items():
            self.execute("UPDATE document_inbox_items SET sha256 = ? WHERE id = ?",
                         (hashlib.sha256(path.read_bytes()).hexdigest(), item_id))
        self.copy = self.patch(document_inbox_service, "copy_inbox_item_to_expedient_box", wraps=REAL_COPY)
        self.patch(archive, "EXECUTION_ENABLED", True)

    def tearDown(self):
        self.assertEqual(self.db_violations, [])
        self.assertEqual(self.real_db_state(), self.real_db_before)
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def real_db_state():
        return REAL_DB.stat().st_mtime_ns if REAL_DB.exists() else None

    def snapshot(self):
        return (self.rows(), self.events(), self.tree(), self.schema(),
                self.query("SELECT * FROM document_viewer_notes"))

    def source(self, item_id):
        return self.inbox_docs[item_id].read_bytes()

    def link_items(self, *ids, client_id=7, expedient_id=42):
        for item_id in ids:
            self.execute("UPDATE document_inbox_items SET status = 'linked', client_id = ?, expedient_id = ? "
                         "WHERE id = ?", (client_id, expedient_id, item_id))

    def prepare(self, ids, *, folder=None, choices=None, actor="default", client_id=7, expedient_id=42):
        return archive.prepare_archive(self.actor if actor == "default" else actor,
                                       [self.doc(item_id) for item_id in ids], client_id=client_id,
                                       expedient_id=expedient_id, folder=folder, choices=choices,
                                       db_path=self.db)

    @staticmethod
    def run_plan(plan):
        return archive.execute_archive(plan, confirmed=True, fingerprint=plan.fingerprint)

    @staticmethod
    def outcomes(result):
        return [(item.inbox_item_id, item.status) for item in result.items]

    def copied_ids(self):
        return [call.args[0] for call in self.copy.call_args_list]

    def assert_added(self, before, added):
        """Exactly ``added`` appeared under archivo/; every previous entry is intact."""
        old = {path: (kind, data) for path, kind, data in before}
        new = {path: (kind, data) for path, kind, data in self.tree()}
        self.assertEqual({path: value for path, value in new.items() if path not in old}, added)
        self.assertEqual({path: new.get(path) for path in old}, old)
        self.archive_before = self.tree()

    def archive_form(self):
        form = self.page.overlay[-1].data
        self.assertIsInstance(form, archive_dialog.ArchiveForm)
        return form

    def open_archive(self, dialog, command="Archivar en Box"):
        self.button(dialog, command).on_click(None)
        return self.archive_form()


class ScopeTests(ArchiveBase):
    def test_link_dialog_only_opens_the_archive_dialog(self):
        source = dv24.DIALOG.read_text(encoding="utf-8")
        for name in (*COPY_NAMES, "box_archive_service"):
            self.assertNotIn(name, source)
        self.assertIsNone(re.search(r"document_inbox_service\.\w+\(", source))
        tree = ast.parse(source)
        top_level = {node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
        # Late import: the dialog module is only loaded when the archive is opened.
        self.assertNotIn("frontend.components.document_viewer_archive_dialog", top_level)
        self.assertIn("frontend.components.document_viewer_archive_dialog", dv24.imported_modules(dv24.DIALOG))
        self.assertEqual(p3a.called_names(dv24.DIALOG) & p3a.FORBIDDEN_CALLS, set())
        self.assertIn("link_service.execute_link(", source)

    def test_archive_dialog_only_talks_to_the_archive_service(self):
        source = ARCHIVE_DIALOG.read_text(encoding="utf-8")
        for name in (*COPY_NAMES, "document_inbox_service", "filing_plan_service", "link_service"):
            self.assertNotIn(name, source)
        modules = dv24.imported_modules(ARCHIVE_DIALOG)
        for forbidden in ("shutil", "os", "pathlib", "sqlite3", "database", "subprocess"):
            self.assertFalse(any(m == forbidden or m.startswith(forbidden + ".") for m in modules), forbidden)
        calls = {node.func.attr for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and getattr(node.func.value, "id", None) == "archive_service"}
        self.assertEqual(calls, {"execution_blocker", "inspect_archive", "prepare_archive", "execute_archive"})
        self.assertEqual(p3a.called_names(ARCHIVE_DIALOG) & p3a.FORBIDDEN_CALLS, set())

    def test_service_reuses_the_certified_copy_and_otherwise_reads(self):
        source = SERVICE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertEqual(set(re.findall(r"document_inbox_service\.(\w+)", source)),
                         {"copy_inbox_item_to_expedient_box", "BoxCopyIncomplete", "INBOX_ROOT"})
        copies = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and getattr(node.func, "attr", None) == "copy_inbox_item_to_expedient_box"]
        self.assertEqual(len(copies), 1)
        self.assertEqual({keyword.arg for keyword in copies[0].keywords},
                         {"expedient_id", "subfolder", "nomenclature_key"})
        self.assertEqual(p3a.attributes_of(SERVICE, "connection"), {"get_readonly_connection", "DB_PATH"})
        modules = dv24.imported_modules(SERVICE)
        for forbidden in ("shutil", "nt", "posix", "subprocess", "backend.services.box_watch_service"):
            self.assertFalse(any(m == forbidden or m.startswith(forbidden + ".") for m in modules), forbidden)
        self.assertFalse(any(m.startswith("os.") for m in modules))
        # DV28-GATE-FIX: ``os`` is imported plainly and used ONLY to read the gate variable,
        # os.environ.get("QUESADA_VIEWER_BOX_COPY_ENABLED"); no other os attribute, alias or rebinding.
        self.assertEqual([[(alias.name, alias.asname) for alias in node.names] for node in ast.walk(tree)
                          if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "os" for a in node.names)],
                         [[("os", None)]])
        self.assertEqual([node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                          and (node.module or "").split(".")[0] in ("os", "nt", "posix")], [])
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        uses = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "os"]
        self.assertEqual(len(uses), 1)
        for name in uses:
            environ = parents.get(name)
            get = parents.get(environ)
            call = parents.get(get)
            self.assertIsInstance(name.ctx, ast.Load)
            self.assertTrue(isinstance(environ, ast.Attribute) and environ.attr == "environ"
                            and isinstance(environ.ctx, ast.Load))
            self.assertTrue(isinstance(get, ast.Attribute) and get.attr == "get" and get.value is environ)
            self.assertTrue(isinstance(call, ast.Call) and call.func is get and not call.keywords)
            self.assertEqual([(type(arg), getattr(arg, "value", None)) for arg in call.args],
                             [(ast.Constant, "QUESADA_VIEWER_BOX_COPY_ENABLED")])
        banned = {"mkdir", "makedirs", "rename", "unlink", "remove", "rmdir", "rmtree", "copy2", "copyfile",
                  "copytree", "move", "touch", "write_text", "write_bytes", "symlink", "commit",
                  "executescript", "get_connection", "get_existing_connection", "link_inbox_item",
                  "update_inbox_item_status", "update_inbox_item_filename", "import_file_to_inbox",
                  "copy_document_inbox_batch_to_expedient_box", "ensure_schema",
                  "ensure_document_inbox_schema", "get_inbox_item", "removedirs", "renames", "link",
                  "truncate", "chmod", "utime", "system", "popen", "startfile", "putenv", "unsetenv",
                  "getenv", "__import__", "import_module"}
        self.assertEqual(p3a.called_names(SERVICE) & banned, set())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "execute":
                self.assertTrue(node.args[0].value.lstrip().upper().startswith("SELECT"))
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "open":
                self.assertEqual(node.args[0].value, "rb")
        # P3A planner and P3B1 copy are reused, not modified: their contracts still hold.
        self.assertNotIn("copy_inbox_item_to_expedient_box", p3a.FILING.read_text(encoding="utf-8"))


class GateTests(ArchiveBase):
    def test_real_path_is_closed_in_the_code(self):
        tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
        values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
                  and any(getattr(target, "id", None) == "EXECUTION_ENABLED" for target in node.targets)]
        self.assertEqual(values, [False])
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        self.assertEqual(len(plan.ready), 1)
        before = self.snapshot()
        for closed in (False, None, 1, "True"):
            with self.subTest(gate=closed), patch.object(archive, "EXECUTION_ENABLED", closed), \
                    patch.dict(os.environ, without_gate_env(), clear=True):
                self.assertEqual(archive.execution_blocker(), archive.EXECUTION_DISABLED)
                with self.assertRaises(archive.ArchiveError) as raised:
                    self.run_plan(plan)
                self.assertEqual(str(raised.exception), archive.EXECUTION_DISABLED)
        self.assertIsNone(plan.result)
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()
        # Only the sandbox opened it for the other suites.
        self.assertEqual(archive.execution_blocker(), "")

    def test_with_the_gate_closed_the_dialog_only_reviews(self):
        dialog = self.open_inbox([6, 1])
        before = self.snapshot()
        with patch.object(archive, "EXECUTION_ENABLED", False), \
                patch.dict(os.environ, without_gate_env(), clear=True), self.guard():
            form = self.open_archive(dialog)
            self.assertIn(archive.EXECUTION_DISABLED, self.texts(form.dialog))
            self.assertEqual(form.submit_button.tooltip, archive.EXECUTION_DISABLED)
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · SOLICITANTE")
            self.assertEqual(len(form.plan.ready), 1)
            self.assertTrue(form.confirm.disabled)
            self.assertTrue(form.submit_button.disabled)
            self.confirm(form)  # even when forced, the consent is not taken
            self.assertIsNone(form.consented)
            self.assertTrue(form.submit_button.disabled)
            self.assertIsNone(form.submit())
            form.close()
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)


class ReviewTests(ArchiveBase):
    def test_inspection_reads_eligibility_and_the_linked_destination(self):
        before = self.snapshot()
        inspection = archive.inspect_archive(
            self.actor, [self.doc(6), self.doc(1), self.doc(7), self.doc(5), self.doc(8), self.doc(99),
                         self.box_doc(), self.doc(6)], db_path=self.db)
        self.assertEqual(inspection.target, link_service.LinkTarget(7, 42, dv24.TARGET))
        self.assertEqual(inspection.message, "")
        self.assertEqual([(item.outcome, item.message) for item in inspection.items], [
            (archive.READY, ""), (archive.REJECTED, archive.NOT_LINKED),
            (archive.REJECTED, archive.ALREADY_COPIED), (archive.REJECTED, archive.DISCARDED),
            (archive.REJECTED, archive.DUPLICATE), (archive.REJECTED, link_service.ITEM_MISSING),
            (archive.NOT_ARCHIVABLE, archive.NO_INBOX), (archive.REJECTED, archive.REPEATED)])
        cases = {
            "mixed destinations": ([self.doc(6), self.doc(4)], archive.MIXED_TARGETS),
            "only expediente files": ([self.box_doc(0), self.box_doc(1)], archive.NO_INBOX),
            "not linked": ([self.doc(1)], archive.NOTHING_TO_ARCHIVE),
            "another item's file": ([self.doc(6, path=self.inbox_docs[1])], archive.NOTHING_TO_ARCHIVE),
        }
        for name, (documents, message) in cases.items():
            with self.subTest(name):
                inspection = archive.inspect_archive(self.actor, documents, db_path=self.db)
                self.assertIsNone(inspection.target)
                self.assertEqual(inspection.message, message)
                self.assertNotIn(archive.READY, [item.outcome for item in inspection.items])
        wrong = archive.inspect_archive(self.actor, [self.doc(6, path=self.inbox_docs[1])], db_path=self.db)
        self.assertEqual(wrong.items[0].message, link_service.WRONG_FILE)
        # The linked expediente was archived in the CRM: no destination.
        self.execute("UPDATE expedientes SET activo = 0 WHERE id = 42")
        inspection = archive.inspect_archive(self.actor, [self.doc(6)], db_path=self.db)
        self.assertIsNone(inspection.target)
        self.assertIn("archivado", inspection.message)
        self.execute("UPDATE expedientes SET activo = 1 WHERE id = 42")
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    def test_session_user_is_verified(self):
        for actor, message in ((None, archive.NO_ACTOR), ({"id": 99}, archive.NOT_AUTHORIZED),
                               ({"id": 3, "username": "baja"}, archive.NOT_AUTHORIZED),
                               ({"id": 1, "username": "luis"}, archive.NOT_AUTHORIZED)):
            with self.subTest(actor=actor):
                with self.assertRaises(archive.ArchiveError) as raised:
                    archive.inspect_archive(actor, [self.doc(6)], db_path=self.db)
                self.assertEqual(str(raised.exception), message)
                with self.assertRaises(archive.ArchiveError) as raised:
                    self.prepare([6], folder="", choices={"inbox:6": K[0]}, actor=actor)
                self.assertEqual(str(raised.exception), message)
        # The user is deactivated between the review and the confirmation.
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        self.execute("UPDATE users SET is_active = 0 WHERE id = 1")
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(plan)
        self.assertEqual(str(raised.exception), archive.NOT_AUTHORIZED)
        self.assertIsNone(plan.result)
        self.copy.assert_not_called()

    def test_review_projects_names_and_collisions_without_reserving(self):
        self.link_items(1, 2, 3)
        before = self.snapshot()
        choices = {"inbox:1": K[0], "inbox:2": K[0], "inbox:3": K[3]}
        plan = self.prepare([1, 2, 3, 6], folder="01 IDENTIDAD", choices=choices)
        self.assertEqual((plan.folder, plan.folder_label), ("01 IDENTIDAD", "01 IDENTIDAD"))
        self.assertEqual([(item.inbox_item_id, item.outcome, item.proposed_name) for item in plan.items], [
            (1, archive.READY, "PASAPORTE SOLICITANTE_2.pdf"), (2, archive.READY, "PASAPORTE SOLICITANTE_3.pdf"),
            (3, archive.READY, "ADMISIÓN A TRÁMITE.pdf"), (6, archive.PENDING, "")])
        self.assertEqual(plan.items[3].message, "Elige una nomenclatura del catálogo del expediente.")
        self.assertEqual([item.nomenclature_key for item in plan.ready], [K[0], K[0], K[3]])
        self.assertEqual(plan.items[0].nomenclature_label, "PASAPORTE · SOLICITANTE")
        self.assertIn("sin sobrescribir", plan.items[0].message)
        self.assertEqual(plan.items[2].message, "Se copiará como «ADMISIÓN A TRÁMITE.pdf».")
        self.assertRegex(plan.fingerprint, r"^[0-9a-f]{64}$")
        # Deterministic review, but every review is its own plan.
        again = self.prepare([1, 2, 3, 6], folder="01 IDENTIDAD", choices=choices)
        self.assertEqual(again.fingerprint, plan.fingerprint)
        self.assertNotEqual(again.token, plan.token)
        root = self.prepare([1, 2, 3, 6], folder="", choices=choices)
        self.assertNotEqual(root.fingerprint, plan.fingerprint)
        self.assertEqual(root.folder_label, filing.ROOT_LABEL)
        self.assertEqual([item.proposed_name for item in root.ready],
                         ["PASAPORTE SOLICITANTE.pdf", "PASAPORTE SOLICITANTE_2.pdf", "ADMISIÓN A TRÁMITE.pdf"])
        # Untrusted folders: traversal, absolute, hidden, missing or not text.
        for folder in ("../fuera", "..", "01 IDENTIDAD/../..", str(self.box / "01 IDENTIDAD"), "C:/Windows",
                       "\\\\servidor\\x", ".oculta", "~temporal", "no-existe", 42, b"01 IDENTIDAD",
                       ["01 IDENTIDAD"]):
            with self.subTest(folder=folder):
                plan = self.prepare([6], folder=folder, choices={"inbox:6": K[0]})
                self.assertEqual((plan.folder, plan.ready, plan.items[0].outcome), (None, (), archive.PENDING))
        # Untrusted nomenclatures: a label, another expediente's key, not text, not a mapping.
        for choice in ({"inbox:6": "PASAPORTE · SOLICITANTE"}, {"inbox:6": "EXPEDIENTE:102:"},
                       {"inbox:6": 0}, {6: K[0]}, ["inbox:6"], None):
            with self.subTest(choices=choice):
                plan = self.prepare([6], folder="", choices=choice)
                self.assertEqual((plan.folder, plan.ready, plan.items[0].outcome), ("", (), archive.PENDING))
        self.assertFalse((self.box / "01 IDENTIDAD" / "PASAPORTE SOLICITANTE_2.pdf").exists())
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    def test_only_documents_already_linked_to_the_same_destination(self):
        self.execute("UPDATE document_inbox_items SET status = 'linked', client_id = NULL, expedient_id = 42 "
                     "WHERE id = 3")
        self.execute("UPDATE document_inbox_items SET status = 'linked', client_id = 7, expedient_id = NULL "
                     "WHERE id = 2")
        before = self.snapshot()
        plan = self.prepare([6, 4, 3, 2], folder="", choices={f"inbox:{i}": K[1] for i in (6, 4, 3, 2)})
        self.assertEqual([(item.inbox_item_id, item.outcome, item.message) for item in plan.items], [
            (6, archive.READY, "Se copiará como «CONTRATO DE TRABAJO.pdf»."),
            (4, archive.REJECTED, archive.OTHER_TARGET), (3, archive.REJECTED, archive.NOT_LINKED),
            (2, archive.REJECTED, archive.NOT_LINKED)])
        # Another expediente of the same client: the archive never moves a link.
        other = self.prepare([6], client_id=7, expedient_id=43, folder="", choices={"inbox:6": "EXPEDIENTE:102:"})
        self.assertEqual((other.items[0].outcome, other.items[0].message), (archive.REJECTED, archive.OTHER_TARGET))
        for client_id, expedient_id, message in ((8, 42, "no pertenece"), (7, 999, "no existe"),
                                                 (7, 51, "archivado"), (7, 52, "no tiene cliente"),
                                                 (None, 42, "Selecciona")):
            with self.subTest(client=client_id, expedient=expedient_id):
                with self.assertRaises(archive.ArchiveError) as raised:
                    self.prepare([6], client_id=client_id, expedient_id=expedient_id, folder="")
                self.assertIn(message, str(raised.exception))
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    def test_links_inside_the_box_root_are_never_a_destination(self):
        link = self.box / "enlace"
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(self.root / "fuera"), str(link))
            self.addCleanup(os.rmdir, link)
        else:
            os.symlink(self.root / "fuera", link, target_is_directory=True)
            self.addCleanup(os.unlink, link)
        self.archive_before = self.tree()
        for folder in ("enlace", "enlace/secreta"):
            with self.subTest(folder=folder):
                plan = self.prepare([6], folder=folder, choices={"inbox:6": K[0]})
                self.assertEqual((plan.folder, plan.ready), (None, ()))
                self.assertNotIn(folder, [option.relative for option in plan.context.folders])
        self.copy.assert_not_called()
        self.assertEqual(sorted(p.name for p in (self.root / "fuera").rglob("*")), ["secreta"])


class ExecutionTests(ArchiveBase):
    def test_single_copy_is_verified_registered_and_keeps_the_link(self):
        before_row = self.row(6)
        plan = self.prepare([6], folder="01 IDENTIDAD", choices={"inbox:6": K[0]})
        self.assertEqual(plan.ready[0].proposed_name, "PASAPORTE SOLICITANTE_2.pdf")
        twin = copy.copy(plan)  # same review object handed around (replay attempt)
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.copy.assert_called_once_with(6, expedient_id=42, subfolder="01 IDENTIDAD", nomenclature_key=K[0])
        outcome, = result.items
        self.assertEqual((outcome.status, outcome.final_name, outcome.destination, outcome.collision),
                         (archive.ARCHIVED, "PASAPORTE SOLICITANTE_2.pdf",
                          "01 IDENTIDAD/PASAPORTE SOLICITANTE_2.pdf", "renamed"))
        self.assertEqual((result.complete, result.partial, result.atomic), (True, False, False))
        self.assertEqual(result.summary, "1 archivado(s) de 1")
        self.assertEqual((result.user, result.folder), ({"id": 1, "username": "ana"}, "01 IDENTIDAD"))
        after = self.row(6)
        # No link transition: same client and expediente, only the copy is registered.
        self.assertEqual((after["status"], after["client_id"], after["expedient_id"]), ("copied_to_box", 7, 42))
        dest = self.box / "01 IDENTIDAD" / "PASAPORTE SOLICITANTE_2.pdf"
        self.assertEqual(Path(after["copied_to_box_path"]).resolve(), dest.resolve())
        for column in ("stored_path", "stored_filename", "original_filename", "sha256", "notes", "metadata_json"):
            self.assertEqual(after[column], before_row[column], column)
        self.assertEqual([event["event_type"] for event in self.events(6)], ["copied_to_box"])
        # The existing homonym is intact; only the new copy appeared, identical to the source.
        self.assert_added(tree, {"EXP-42/01 IDENTIDAD/PASAPORTE SOLICITANTE_2.pdf": ("file", self.source(6))})
        # Replays: same plan returns the same result, a copy of it is refused, nothing is copied again.
        self.assertIs(self.run_plan(plan), result)
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(twin)
        self.assertEqual(str(raised.exception), archive.REPLAYED)
        self.assertEqual(self.copy.call_count, 1)
        again = archive.inspect_archive(self.actor, [self.doc(6)], db_path=self.db)
        self.assertEqual((again.items[0].outcome, again.items[0].message), (archive.REJECTED, archive.ALREADY_COPIED))

    def test_batch_of_four_runs_in_order_and_reports_each_document(self):
        self.link_items(1, 2, 3)

        def answer(item_id, **kwargs):
            if item_id == 2:
                raise document_inbox_service.BoxCopyRejected("Rechazo simulado de la copia.")
            return REAL_COPY(item_id, **kwargs)

        self.copy.side_effect = answer
        plan = self.prepare([1, 2, 3, 6], folder="", choices={"inbox:1": K[1], "inbox:2": K[0],
                                                              "inbox:3": K[0], "inbox:6": K[3]})
        self.assertEqual([item.proposed_name for item in plan.ready], [
            "CONTRATO DE TRABAJO.pdf", "PASAPORTE SOLICITANTE.pdf", "PASAPORTE SOLICITANTE_2.pdf",
            "ADMISIÓN A TRÁMITE.pdf"])
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.copied_ids(), [1, 2, 3, 6])
        self.assertEqual(self.outcomes(result), [(1, archive.ARCHIVED), (2, archive.REJECTED),
                                                 (3, archive.ARCHIVED), (6, archive.ARCHIVED)])
        self.assertEqual(result.items[1].message, "Rechazo simulado de la copia.")
        # The skipped document frees its projected name: the effective one is reported.
        self.assertEqual(result.items[2].final_name, "PASAPORTE SOLICITANTE.pdf")
        self.assertIn("Nombre previsto: «PASAPORTE SOLICITANTE_2.pdf»", result.items[2].message)
        self.assertEqual((result.archived, result.problems, result.partial, result.complete), (3, 1, True, False))
        self.assertEqual(result.summary, "3 archivado(s) de 4 · 1 rechazado(s)")
        self.assertEqual((self.row(2)["status"], self.row(2)["copied_to_box_path"]), ("linked", None))
        self.assert_added(tree, {"EXP-42/CONTRATO DE TRABAJO.pdf": ("file", self.source(1)),
                                 "EXP-42/PASAPORTE SOLICITANTE.pdf": ("file", self.source(3)),
                                 "EXP-42/ADMISIÓN A TRÁMITE.pdf": ("file", self.source(6))})

    def test_unregistered_copy_stops_the_batch_for_review(self):
        """Residual risk (P3B1): another process registers a copy of the same item meanwhile."""
        self.link_items(1, 2)
        real_create = document_inbox_service._create_box_copy
        other = str(self.box / "02 LABORAL" / "copia de otro equipo.pdf")

        def racing(*args, **kwargs):
            created = real_create(*args, **kwargs)
            self.execute("UPDATE document_inbox_items SET status = 'copied_to_box', copied_to_box_path = ? "
                         "WHERE id = 1", (other,))
            return created

        self.patch(document_inbox_service, "_create_box_copy", side_effect=racing)
        plan = self.prepare([1, 2, 6], folder="02 LABORAL", choices={"inbox:1": K[1], "inbox:2": K[2],
                                                                    "inbox:6": K[3]})
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.copied_ids(), [1])
        self.assertEqual(self.outcomes(result), [(1, archive.INCOMPLETE), (2, archive.NOT_ATTEMPTED),
                                                 (6, archive.NOT_ATTEMPTED)])
        written = self.box / "02 LABORAL" / "CONTRATO DE TRABAJO.pdf"
        self.assertEqual(Path(result.items[0].written_path).resolve(), written.resolve())
        self.assertIn("Requiere revisión humana", result.items[0].message)
        self.assertEqual(result.items[1].message, archive.NOT_ATTEMPTED_MESSAGE)
        self.assertEqual((result.archived, result.complete), (0, False))
        self.assertEqual(self.row(1)["copied_to_box_path"], other)
        self.assertEqual([event["event_type"] for event in self.events(1)], ["copy_to_box_failed"])
        self.assertEqual([self.row(i)["status"] for i in (2, 6)], ["linked", "linked"])
        # The extra copy stays for human review: it is never deleted.
        self.assert_added(tree, {"EXP-42/02 LABORAL/CONTRATO DE TRABAJO.pdf": ("file", self.source(1))})

    def test_identical_file_is_reused_never_duplicated_or_overwritten(self):
        same = self.box / "01 IDENTIDAD" / "PASAPORTE SOLICITANTE_2.pdf"
        same.write_bytes(self.source(6))
        self.archive_before = self.tree()
        plan = self.prepare([6], folder="01 IDENTIDAD", choices={"inbox:6": K[0]})
        self.assertEqual(plan.ready[0].proposed_name, "PASAPORTE SOLICITANTE_3.pdf")
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        outcome, = result.items
        self.assertEqual((outcome.status, outcome.final_name, outcome.collision),
                         (archive.ARCHIVED, "PASAPORTE SOLICITANTE_2.pdf", "reused_identical"))
        self.assertIn("se registra sin duplicarlo", outcome.message)
        self.assertIn("Nombre previsto: «PASAPORTE SOLICITANTE_3.pdf»", outcome.message)
        self.assert_added(tree, {})
        self.assertEqual(Path(self.row(6)["copied_to_box_path"]).resolve(), same.resolve())

    def test_changes_between_review_and_execution_copy_nothing(self):
        path = self.inbox_docs[6]
        data, stat = path.read_bytes(), path.stat()
        taken = self.box / "01 IDENTIDAD" / "PASAPORTE SOLICITANTE_2.pdf"
        contratos = self.box / "02 LABORAL" / "Contratos"

        def restore_source():
            path.write_bytes(data)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

        def item(sql, params=()):
            return lambda: self.execute(f"UPDATE document_inbox_items SET {sql} WHERE id = 6", params)

        cases = {
            "source content": ("01 IDENTIDAD", lambda: path.write_bytes(data + b"\n%cambio"), restore_source),
            "relinked elsewhere": ("01 IDENTIDAD", item("expedient_id = 43"), item("expedient_id = 42")),
            "item updated": ("01 IDENTIDAD", item("updated_at = '2026-11-10 09:00:00'"),
                             item("updated_at = '2026-11-01 10:00:00'")),
            "source replaced": ("01 IDENTIDAD", item("stored_path = ?", (str(self.inbox_docs[2]),)),
                                item("stored_path = ?", (str(path),))),
            "name taken meanwhile": ("01 IDENTIDAD", lambda: taken.write_bytes(b"otro"), taken.unlink),
            "folder removed": ("02 LABORAL/Contratos", contratos.rmdir, contratos.mkdir),
            "box root changed": ("01 IDENTIDAD", lambda: self.set_box(42, str(self.box43)),
                                 lambda: self.set_box(42, str(self.box))),
        }
        for name, (folder, change, undo) in cases.items():
            with self.subTest(name):
                plan = self.prepare([6], folder=folder, choices={"inbox:6": K[0]})
                self.assertEqual(len(plan.ready), 1)
                change()
                before = (self.rows(), self.events(), self.tree())
                with self.assertRaises(archive.ArchiveError) as raised:
                    self.run_plan(plan)
                self.assertEqual(str(raised.exception), archive.STALE)
                self.assertIsNone(plan.result)
                self.assertEqual((self.rows(), self.events(), self.tree()), before)
                undo()
        # The expediente changes owner: the destination itself is refused.
        plan = self.prepare([6], folder="01 IDENTIDAD", choices={"inbox:6": K[0]})
        self.execute("UPDATE expedientes SET cliente_id = 8 WHERE id = 42")
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(plan)
        self.assertIn("no pertenece", str(raised.exception))
        self.execute("UPDATE expedientes SET cliente_id = 7 WHERE id = 42")
        self.copy.assert_not_called()
        self.assertEqual(self.row(6)["status"], "linked")

    def test_each_document_is_revalidated_right_before_its_copy(self):
        self.link_items(1, 2)

        def copy_then_change(item_id, **kwargs):
            updated = REAL_COPY(item_id, **kwargs)
            if item_id == 1:
                self.execute("UPDATE document_inbox_items SET updated_at = '2026-11-10 09:00:00' WHERE id = 2")
            return updated

        self.copy.side_effect = copy_then_change
        plan = self.prepare([1, 2, 6], folder="02 LABORAL", choices={"inbox:1": K[1], "inbox:2": K[2],
                                                                    "inbox:6": K[3]})
        tree = self.tree()
        with self.guard():
            result = self.run_plan(plan)
        self.assertEqual(self.outcomes(result), [(1, archive.ARCHIVED), (2, archive.REJECTED),
                                                 (6, archive.ARCHIVED)])
        self.assertEqual(result.items[1].message, archive.STALE_ITEM)
        self.assertEqual(self.copied_ids(), [1, 6])
        self.assertEqual(self.row(2)["status"], "linked")
        self.assert_added(tree, {"EXP-42/02 LABORAL/CONTRATO DE TRABAJO.pdf": ("file", self.source(1)),
                                 "EXP-42/02 LABORAL/ADMISIÓN A TRÁMITE.pdf": ("file", self.source(6))})

    def test_confirmation_fingerprint_and_untrusted_plan_fields(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        for confirmed in (False, None, "sí", 1):
            with self.subTest(confirmed=confirmed), self.assertRaises(archive.ArchiveError) as raised:
                archive.execute_archive(plan, confirmed=confirmed, fingerprint=plan.fingerprint)
            self.assertEqual(str(raised.exception), archive.NOT_CONFIRMED)
        with self.assertRaises(archive.ArchiveError) as raised:
            archive.execute_archive({"items": []}, confirmed=True, fingerprint="x")
        self.assertEqual(str(raised.exception), archive.INVALID_REQUEST)
        other = self.prepare([6], folder="01 IDENTIDAD", choices={"inbox:6": K[0]})
        for fingerprint in (None, "", "0" * 64, other.fingerprint, plan.fingerprint.upper()):
            with self.subTest(fingerprint=fingerprint), self.assertRaises(archive.ArchiveError) as raised:
                archive.execute_archive(plan, confirmed=True, fingerprint=fingerprint)
            self.assertEqual(str(raised.exception), archive.STALE_CONSENT)
        # Inputs of the review altered after it: the fresh review no longer matches.
        for name, forged in (
                ("folder", replace(plan, folder="../fuera", token=uuid4().hex)),
                ("choices", replace(plan, choices=(("inbox:6", K[1]),), token=uuid4().hex)),
                ("target", replace(plan, target=link_service.LinkTarget(7, 43, "x"), token=uuid4().hex)),
                ("documents", replace(plan, requests=(self.doc(1),), token=uuid4().hex))):
            with self.subTest(forged=name), self.assertRaises(archive.ArchiveError) as raised:
                self.run_plan(forged)
            self.assertEqual(str(raised.exception), archive.STALE)
        self.copy.assert_not_called()
        # Reviewed items altered in the plan object are never used: the fresh review is executed.
        forged = replace(plan, token=uuid4().hex, items=tuple(
            replace(item, nomenclature_key=K[1], proposed_name="CONTRATO DE TRABAJO.pdf") for item in plan.items))
        tree = self.tree()
        with self.guard():
            result = self.run_plan(forged)
        self.copy.assert_called_once_with(6, expedient_id=42, subfolder="", nomenclature_key=K[0])
        self.assertEqual(result.items[0].final_name, "PASAPORTE SOLICITANTE.pdf")
        self.assert_added(tree, {"EXP-42/PASAPORTE SOLICITANTE.pdf": ("file", self.source(6))})
        # The original review is now stale (already copied): nothing is copied twice.
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(plan)
        self.assertEqual(str(raised.exception), archive.STALE)
        self.assertEqual(self.copy.call_count, 1)

    def test_double_click_and_parallel_reviews_are_single_flight(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        parallel = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        entered, release, results = threading.Event(), threading.Event(), []

        def slow(item_id, **kwargs):
            entered.set()
            release.wait(10)
            return REAL_COPY(item_id, **kwargs)

        self.copy.side_effect = slow
        tree = self.tree()
        worker = threading.Thread(target=lambda: results.append(self.run_plan(plan)))
        worker.start()
        try:
            self.assertTrue(entered.wait(10))
            with self.assertRaises(archive.ArchiveError) as raised:
                self.run_plan(plan)  # second click while the first one runs
            self.assertEqual(str(raised.exception), archive.IN_PROGRESS)
            second = self.run_plan(parallel)  # another review of the same document
            self.assertEqual(self.outcomes(second), [(6, archive.REJECTED)])
            self.assertEqual(second.items[0].message, archive.IN_FLIGHT)
        finally:
            release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.outcomes(results[0]), [(6, archive.ARCHIVED)])
        self.assertIs(self.run_plan(plan), results[0])
        self.assertEqual(self.copy.call_count, 1)
        self.assert_added(tree, {"EXP-42/PASAPORTE SOLICITANTE.pdf": ("file", self.source(6))})

    def test_review_from_another_database_is_never_executed(self):
        plan = self.prepare([6], folder="", choices={"inbox:6": K[0]})
        other = self.root / "otra.db"
        with self.assertRaises(archive.ArchiveError) as raised:
            self.run_plan(replace(plan, db_path=other, token=uuid4().hex))
        self.assertEqual(str(raised.exception), archive.OTHER_DATABASE)
        self.assertFalse(other.exists())
        self.assertIsNone(plan.result)
        self.copy.assert_not_called()


class ViewerDialogTests(ArchiveBase):
    def test_entry_point_needs_a_bandeja_source_and_keeps_the_link_form(self):
        dialog = self.open_inbox([6, 1])
        button = self.button(dialog, "Archivar en Box")
        self.assertFalse(button.disabled)
        self.assertEqual(button.tooltip, link_dialog.ARCHIVE_TOOLTIP)
        self.assertNotIn("Archivar seleccionados", self.labels(dialog))
        # DV28-FIX2: LinkForm's combined action is wired but disabled until the link is confirmed.
        form = self.open_form(dialog)
        self.assertTrue(form.archive_button.disabled)
        self.assertEqual(form.archive_button.on_click, form.submit_and_archive)
        self.assertEqual(form.archive_button.tooltip, link_dialog.ARCHIVE_AFTER_LINK)
        # One dialog at a time.
        self.button(dialog, "Archivar en Box").on_click(None)
        self.assertIs(self.page.overlay[-1].data, form)
        form.close()
        self.button(dialog, "Comparador 4").on_click(None)
        selected = self.button(dialog, "Archivar seleccionados")
        self.assertTrue(selected.disabled)
        self.assertIsNone(selected.on_click)
        self.assertEqual(selected.tooltip, link_dialog.NO_ARCHIVE_SELECTION)
        self.check(dialog, 1, True)
        self.assertFalse(self.button(dialog, "Archivar seleccionados").disabled)
        self.button(dialog, "Cerrar").on_click(None)
        # Expediente folder documents have no Bandeja item: disabled, with the reason.
        queue = [{"path": str(path), "name": path.name} for path in self.exp_docs]
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], expediente_id=42, queue=queue,
                                            near_window=0, linking=self.linking())
        button = self.button(dialog, "Archivar en Box")
        self.assertTrue(button.disabled)
        self.assertIsNone(button.on_click)
        self.assertEqual(button.tooltip, link_dialog.NO_ARCHIVE_SOURCE)
        self.button(dialog, "Cerrar").on_click(None)
        self.copy.assert_not_called()

    def test_review_consent_and_single_execution_from_the_viewer(self):
        dialog = self.open_inbox([6, 1])
        layout = viewer_layout(dialog)
        state = (layout.document.index, layout.page_label.value, layout.zoom_label.value)
        link_status = self.links(dialog).status_text.value
        before = self.snapshot()
        with self.guard():
            form = self.open_archive(dialog)
            texts = self.texts(form.dialog)
            self.assertIn(archive.COPY_ONLY, texts)
            self.assertIn(f"Destino: expediente {dv24.TARGET} del cliente #7 (su vinculación actual).", texts)
            self.assertEqual([request["inbox_item_id"] for request in form.requests], [6])
            self.assertEqual(viewer_action_label(form.submit_button), archive_dialog.SUBMIT_LABEL)
            self.assertEqual((form.confirm.value, form.confirm.disabled, form.submit_button.disabled),
                             (False, True, True))
            self.assertEqual(self.labels_of(form.folder_select), p3a.FOLDERS_42)
            self.assertEqual(list(form.nomenclature_selects), ["inbox:6"])
            self.assertEqual(self.labels_of(form.nomenclature_selects["inbox:6"]), p3a.LABELS_42)
            self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · SOLICITANTE")
            self.assertEqual(form.plan.ready, ())  # the folder is still missing
            self.assertTrue(form.confirm.disabled)
            self.choose(form.folder_select, "01 IDENTIDAD")
            self.assertEqual([item.proposed_name for item in form.plan.ready], ["PASAPORTE SOLICITANTE_2.pdf"])
            self.assertEqual((form.confirm.value, form.confirm.disabled, form.submit_button.disabled),
                             (False, False, True))
            self.assertIsNone(form.submit())
            self.assertEqual(form.status.value, archive.NOT_CONFIRMED)
            self.confirm(form)
            self.assertFalse(form.submit_button.disabled)
            self.assertEqual(form.consented, form.plan.fingerprint)
            self.assertIn(f"Confirmo archivar una COPIA de 1 documento(s) en «01 IDENTIDAD» del expediente "
                          f"{dv24.TARGET}", form.confirm.label)
            # Any change drops the consent and the previous review.
            first = form.plan
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.assertIsNot(form.plan, first)
            self.assertEqual((form.consented, form.confirm.value, form.submit_button.disabled), (None, False, True))
            self.assertEqual([item.proposed_name for item in form.plan.ready], ["PASAPORTE SOLICITANTE.pdf"])
            self.assertEqual(self.snapshot(), before)  # reviewing wrote nothing
            self.copy.assert_not_called()
            self.confirm(form)
            form.submit_button.on_click(None)
            form.submit_button.on_click(None)  # double click
        self.copy.assert_called_once_with(6, expedient_id=42, subfolder="", nomenclature_key=K[0])
        self.assertTrue(form.result.complete)
        self.assertEqual(form.status.value, "1 archivado(s) de 1. Por ana.")
        self.assertEqual(form.status.color, archive_dialog.Q_SUCCESS)
        self.assertFalse(form.submit_button.visible)
        self.assertEqual(viewer_action_label(form.cancel_button), "Cerrar")
        self.assertEqual([control.data for control in form.review_column.controls[1:]], [archive.ARCHIVED])
        self.assertIn("«PASAPORTE SOLICITANTE.pdf»", form.review_column.controls[1].value)
        self.assert_added(before[2], {"EXP-42/PASAPORTE SOLICITANTE.pdf": ("file", self.source(6))})
        # The viewer is untouched: document, page, zoom and link state.
        layout = viewer_layout(dialog)
        self.assertEqual((layout.document.index, layout.page_label.value, layout.zoom_label.value), state)
        self.assertEqual(self.links(dialog).status_text.value, link_status)
        form.close()
        # A retry is a new review: the copied document is refused, nothing is duplicated.
        again = self.open_archive(dialog)
        self.assertEqual(again.status.value, archive.NOTHING_TO_ARCHIVE)
        self.assertFalse(again.submit_button.visible)
        self.assertIn(f"Bandeja #6 · {archive.ALREADY_COPIED}", self.texts(again.dialog))
        again.close()
        self.assertEqual(self.copy.call_count, 1)
        self.button(dialog, "Cerrar").on_click(None)

    def test_cancel_close_and_navigation_write_nothing(self):
        dialog = self.open_inbox([6, 2, 3], notes=self.notes())
        self.button(dialog, "Zoom +").on_click(None)
        layout = viewer_layout(dialog)
        state = (layout.document.index, layout.page_label.value, layout.zoom_label.value)
        before = self.snapshot()
        with self.guard():
            for how in ("cancel", "close"):
                with self.subTest(how=how):
                    form = self.open_archive(dialog)
                    self.choose(form.folder_select, "01 IDENTIDAD")
                    self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · FAMILIAR")
                    self.confirm(form)
                    plan, folder_select = form.plan, form.folder_select
                    form.cancel_button.on_click(None) if how == "cancel" else form.close()
                    self.assertTrue(form.closed)
                    self.assertIsNone(form.submit())
                    self.choose(folder_select, filing.ROOT_LABEL)  # late event after closing
                    self.assertIs(form.plan, plan)
                    layout = viewer_layout(dialog)
                    self.assertEqual((layout.document.index, layout.page_label.value,
                                      layout.zoom_label.value), state)
            self.button(dialog, "Doc siguiente").on_click(None)
            self.button(dialog, "Doc anterior").on_click(None)
            self.assertEqual(viewer_layout(dialog).document.index, 0)
            # Closing the viewer with the dialog open closes it; nothing is written.
            form = self.open_archive(dialog)
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.button(dialog, "Cerrar").on_click(None)
            self.assertTrue(form.closed)
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()

    def test_linking_writes_nothing_in_box_and_then_the_copy_keeps_the_link(self):
        dialog = self.open_inbox([2, 6])
        tree = self.tree()
        with self.guard():
            form = self.open_archive(dialog)  # item 2 is pending: not archivable yet
            self.assertEqual(form.status.value, archive.NOTHING_TO_ARCHIVE)
            self.assertFalse(form.submit_button.visible)
            self.assertIn(f"Bandeja #2 · {archive.NOT_LINKED}", self.texts(form.dialog))
            form.close()
            link = self.open_form(dialog)
            self.pick(link.expedient_select, 42)
            self.confirm(link)
            link.submit_button.on_click(None)
            self.assertEqual(self.statuses(link.result), {2: link_service.LINKED})
            link.close()
            self.copy.assert_not_called()
            self.assertEqual(self.tree(), tree)
            form = self.open_archive(dialog)
            self.choose(form.folder_select, "02 LABORAL/Contratos")
            self.choose(form.nomenclature_selects["inbox:2"], "CONTRATO DE TRABAJO")
            self.confirm(form)
            form.submit_button.on_click(None)
        row = self.row(2)
        self.assertEqual((row["status"], row["client_id"], row["expedient_id"]), ("copied_to_box", 7, 42))
        self.assertEqual([event["event_type"] for event in self.events(2)], ["linked", "copied_to_box"])
        self.assert_added(tree, {"EXP-42/02 LABORAL/Contratos/CONTRATO DE TRABAJO.pdf": ("file", self.source(2))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_link_and_archive_links_then_reviews_with_the_choices_and_its_own_consent(self):
        """DV28-FIX2: «Vincular y archivar copia» = the confirmed link, then the existing archive review."""
        dialog = self.open_inbox([2, 6])
        tree = self.tree()
        with self.guard():
            link = self.open_form(dialog)
            self.assertTrue(link.archive_button.disabled)
            self.pick(link.expedient_select, 42)
            self.choose(link.folder_select, "02 LABORAL/Contratos")
            self.choose(link.nomenclature_selects["inbox:2"], "CONTRATO DE TRABAJO")
            self.assertTrue(link.archive_button.disabled)  # Box choices alone never enable it
            self.confirm(link)
            self.assertFalse(link.archive_button.disabled)
            choices = dict(link.choices)
            link.archive_button.on_click(None)
            link.archive_button.on_click(None)  # double click
            self.assertEqual(self.statuses(link.result), {2: link_service.LINKED})
            self.assertEqual(self.link.call_count, 1)
            self.assertTrue(link.closed)
            # Linked, nothing copied yet: the archive dialog opens with the choices preselected.
            self.copy.assert_not_called()
            self.assertEqual(self.tree(), tree)
            form = self.archive_form()
            self.assertEqual([request["inbox_item_id"] for request in form.requests], [2])
            self.assertEqual((form.folder, form.choices), ("02 LABORAL/Contratos", choices))
            self.assertEqual(form.folder_select.value, "02 LABORAL/Contratos")
            self.assertEqual(form.nomenclature_selects["inbox:2"].value, "CONTRATO DE TRABAJO")
            self.assertEqual([item.proposed_name for item in form.plan.ready], ["CONTRATO DE TRABAJO.pdf"])
            # Its own consent, never the link one.
            self.assertEqual((form.confirm.value, form.consented, form.submit_button.disabled), (False, None, True))
            self.assertIsNone(form.submit())
            self.copy.assert_not_called()
            self.confirm(form)
            form.submit_button.on_click(None)
            form.submit_button.on_click(None)  # double click
        self.assertEqual(self.copy.call_count, 1)
        self.assertTrue(form.result.complete)
        row = self.row(2)
        self.assertEqual((row["status"], row["client_id"], row["expedient_id"]), ("copied_to_box", 7, 42))
        self.assertEqual([event["event_type"] for event in self.events(2)], ["linked", "copied_to_box"])
        self.assert_added(tree, {"EXP-42/02 LABORAL/Contratos/CONTRATO DE TRABAJO.pdf": ("file", self.source(2))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_link_and_archive_never_copies_a_document_whose_link_failed(self):
        def flaky(item_id, **kwargs):
            if item_id == 2:
                raise RuntimeError("disco lleno")
            return self.canonical(item_id, **kwargs)

        self.link.side_effect = flaky
        dialog = self.open_inbox([1, 2])
        self.button(dialog, "Comparador 4").on_click(None)
        self.check(dialog, 0, True)
        self.check(dialog, 1, True)
        tree = self.tree()
        with self.guard():
            link = self.open_form(dialog, "Vincular seleccionados")
            self.pick(link.expedient_select, 42)
            self.choose(link.folder_select, filing.ROOT_LABEL)
            self.choose(link.nomenclature_selects["inbox:1"], "PASAPORTE · SOLICITANTE")
            self.choose(link.nomenclature_selects["inbox:2"], "CONTRATO DE TRABAJO")
            self.confirm(link)
            link.archive_button.on_click(None)
            self.assertEqual(self.statuses(link.result), {1: link_service.LINKED, 2: link_service.FAILED})
            # Partial result: only the linked document goes on, and the dialog says why.
            form = self.archive_form()
            self.assertEqual([request["inbox_item_id"] for request in form.requests], [1])
            self.assertEqual(set(form.choices), {"inbox:1"})
            self.assertIn(link_dialog.NOT_LINKED_NOT_ARCHIVED.format(count=1), self.texts(form.dialog))
            self.confirm(form)
            form.submit_button.on_click(None)
        self.assertEqual(self.copied_ids(), [1])
        self.assertEqual(self.row(2)["expedient_id"], None)
        self.assert_added(tree, {"EXP-42/PASAPORTE SOLICITANTE.pdf": ("file", self.source(1))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_link_and_archive_stops_when_nothing_was_linked(self):
        self.link.side_effect = RuntimeError("disco lleno")
        dialog = self.open_inbox([1, 2])
        before = self.snapshot()
        with self.guard():
            link = self.open_form(dialog)
            self.pick(link.expedient_select, 42)
            self.choose(link.folder_select, filing.ROOT_LABEL)
            self.confirm(link)
            self.assertIsNotNone(link.archive_button.on_click(None))
            self.assertEqual(self.statuses(link.result), {1: link_service.FAILED})
            # The result stays in the link dialog; no archive review is opened.
            self.assertFalse(link.closed)
            self.assertIs(self.page.overlay[-1].data, link)
            self.assertIsNone(self.links(dialog).archive_form)
            self.assertFalse(link.archive_button.visible)
            self.assertIsNone(link.archive_button.on_click(None))
            link.close()
        self.assertEqual(self.snapshot(), before)
        self.copy.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_comparator_selection_is_a_stable_snapshot_and_archives_four(self):
        self.link_items(1, 2, 3)
        dialog = self.open_inbox([6, 1, 2, 3])
        self.button(dialog, "Comparador 4").on_click(None)
        for tile in range(4):
            self.check(dialog, tile, True)
        tree = self.tree()
        form = self.open_archive(dialog, "Archivar seleccionados")
        self.assertEqual(form.dialog.title.value, "Archivar copia en Box · 4 documentos")
        self.assertIn(archive.BATCH_POLICY, self.texts(form.dialog))
        self.assertEqual([request["inbox_item_id"] for request in form.requests], [6, 1, 2, 3])
        # Changing the comparator selection afterwards does not change what this dialog archives.
        self.check(dialog, 3, False)
        self.assertEqual([request["inbox_item_id"] for request in form.requests], [6, 1, 2, 3])
        self.check(dialog, 3, True)
        with self.guard():
            self.choose(form.folder_select, "02 LABORAL")
            for key, label in (("inbox:6", "PASAPORTE · SOLICITANTE"), ("inbox:1", "CONTRATO DE TRABAJO"),
                               ("inbox:2", "PASAPORTE · FAMILIAR"), ("inbox:3", "ADMISIÓN A TRÁMITE")):
                self.choose(form.nomenclature_selects[key], label)
            self.assertEqual(len(form.plan.ready), 4)
            self.confirm(form)
            form.submit_button.on_click(None)
        self.assertEqual(self.copied_ids(), [6, 1, 2, 3])
        self.assertEqual(form.result.summary, "4 archivado(s) de 4")
        self.assertEqual(form.status.color, archive_dialog.Q_SUCCESS)
        # The link selection is not consumed by the archive.
        self.assertEqual([tile.checkbox.value for tile in viewer_layout(dialog).tiles], [True] * 4)
        self.assertEqual(self.links(dialog).counter_text.value, "4 seleccionados")
        self.assert_added(tree, {f"EXP-42/02 LABORAL/{name}": ("file", self.source(item_id)) for item_id, name in (
            (6, "PASAPORTE SOLICITANTE.pdf"), (1, "CONTRATO DE TRABAJO.pdf"), (2, "PASAPORTE FAMILIAR.pdf"),
            (3, "ADMISIÓN A TRÁMITE.pdf"))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_mixed_destinations_and_partial_failures_are_never_a_success(self):
        self.link_items(1)
        dialog = self.open_inbox([6, 4, 1])
        self.button(dialog, "Comparador 4").on_click(None)
        self.check(dialog, 0, True)
        self.check(dialog, 1, True)
        form = self.open_archive(dialog, "Archivar seleccionados")
        self.assertEqual(form.status.value, archive.MIXED_TARGETS)
        self.assertFalse(form.submit_button.visible)
        form.close()
        self.check(dialog, 1, False)
        self.check(dialog, 2, True)

        def answer(item_id, **kwargs):
            if item_id == 1:
                raise document_inbox_service.BoxCopyRejected("Rechazo simulado de la copia.")
            return REAL_COPY(item_id, **kwargs)

        self.copy.side_effect = answer
        tree = self.tree()
        with self.guard():
            form = self.open_archive(dialog, "Archivar seleccionados")
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.choose(form.nomenclature_selects["inbox:6"], "PASAPORTE · SOLICITANTE")
            self.choose(form.nomenclature_selects["inbox:1"], "CONTRATO DE TRABAJO")
            self.confirm(form)
            form.submit_button.on_click(None)
        self.assertEqual(form.result.summary, "1 archivado(s) de 2 · 1 rechazado(s)")
        self.assertEqual(form.status.color, archive_dialog.Q_WARNING)
        self.assertIn("Resultado parcial: " + archive.BATCH_POLICY, form.status.value)
        self.assertEqual([control.data for control in form.review_column.controls[1:]],
                         [archive.ARCHIVED, archive.REJECTED])
        form.close()
        # Retry: a new review; the archived document is refused, the other one is copied once.
        self.copy.side_effect = None
        with self.guard():
            form = self.open_archive(dialog, "Archivar seleccionados")
            self.assertEqual([item.outcome for item in form.inspection.items], [archive.REJECTED, archive.READY])
            self.assertEqual(list(form.nomenclature_selects), ["inbox:1"])
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.choose(form.nomenclature_selects["inbox:1"], "CONTRATO DE TRABAJO")
            self.confirm(form)
            form.submit_button.on_click(None)
        self.assertEqual(self.copied_ids(), [6, 1, 1])
        self.assertEqual(self.outcomes(form.result), [(6, archive.REJECTED), (1, archive.ARCHIVED)])
        self.assert_added(tree, {"EXP-42/PASAPORTE SOLICITANTE.pdf": ("file", self.source(6)),
                                 "EXP-42/CONTRATO DE TRABAJO.pdf": ("file", self.source(1))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_changes_after_consent_require_a_new_review(self):
        dialog = self.open_inbox([6, 1])
        form = self.open_archive(dialog)
        self.choose(form.folder_select, filing.ROOT_LABEL)
        self.choose(form.nomenclature_selects["inbox:6"], "CONTRATO DE TRABAJO")
        self.confirm(form)
        consented = form.consented
        self.execute("UPDATE document_inbox_items SET updated_at = '2026-11-10 08:00:00' WHERE id = 6")
        self.assertIsNone(form.submit())
        self.assertEqual((form.status.value, form.status.color), (archive.STALE, archive_dialog.Q_ERROR))
        self.assertNotEqual(form.plan.fingerprint, consented)
        self.assertEqual((form.consented, form.confirm.value, form.submit_button.disabled), (None, False, True))
        self.copy.assert_not_called()
        tree = self.tree()
        with self.guard():
            self.confirm(form)
            form.submit_button.on_click(None)
        self.assertTrue(form.result.complete)
        self.assert_added(tree, {"EXP-42/CONTRATO DE TRABAJO.pdf": ("file", self.source(6))})
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_without_a_session_user_nothing_is_reviewed(self):
        dialog = self.open_inbox([6, 1], linking=self.linking(actor=None))
        form = self.open_archive(dialog)
        self.assertEqual(form.status.value, archive.NO_ACTOR)
        self.assertFalse(form.submit_button.visible)
        self.assertIsNone(form.submit())
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        self.copy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
