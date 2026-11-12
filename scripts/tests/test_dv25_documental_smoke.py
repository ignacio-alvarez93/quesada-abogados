"""WO-DV25-C2-C3 · C3: isolation barriers of the DV25 documental smoke.

``scripts/dev/dv25_documental_smoke.py`` is exercised without ever starting Flet or a Flet
client:

- ``--check`` runs in a child process whose ``open``/``os.open``/``mkdir``/``sqlite3.connect``
  kill it on any write or database connection; it must PASS and load neither Flet nor the CRM;
- the smoke's own ``Guards`` are installed in-process over a TemporaryDirectory sandbox and must
  refuse SQLite, writes, processes and network outside it (nothing is ever contacted: the
  guard raises before the real call);
- ``prepare_runtime`` builds the synthetic sandbox (10 PDFs, Bandeja, simulated Box root,
  SQLite) behind those guards, and the REAL viewer (``open_document_viewer_modal``) is opened
  on 2 and 4 marked documents with a fake page: comparator, fold, zoom, notes, link preview,
  archive review (closed gate) and close.

The habitual ``quesada.db`` (+ journal/WAL) is fingerprinted by size, mtime and SHA-256 before
and after the module. Nothing here reaches Box, the habitual CRM or the network.
"""
import ast
from contextlib import closing
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_inbox_service as inbox_service
from backend.services import document_viewer_box_archive_service as archive
from backend.services import document_viewer_filing_plan_service as filing_service
from backend.services import document_viewer_service as viewer_service
from backend.services import expedient_service
from database import connection
from frontend.components import document_viewer_archive_dialog as archive_dialog
from frontend.components import document_viewer_link_dialog as link_dialog
from frontend.components import document_viewer_modal as viewer
from frontend.components import document_viewer_multidoc as multidoc
from frontend.components import document_viewer_notes_panel as notes_panel
from frontend.components import pdf_tools_toolbar_adapter as toolbar_adapter
from scripts.tests import test_document_viewer_dv24_linking as dv24
from scripts.tests import test_document_viewer_dv25_filing_plan as p3a
from scripts.tests import test_document_viewer_dv25_security as security


SCRIPT = Path(__file__).resolve().parents[1] / "dev" / "dv25_documental_smoke.py"
REPO_ROOT = dv24.REPO_ROOT
REPO_PREVIEWS = REPO_ROOT / "data" / "document_previews"


def load_smoke():
    spec = importlib.util.spec_from_file_location("dv25_documental_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load_smoke()
HABITUAL_BEFORE = []


def setUpModule():
    HABITUAL_BEFORE[:] = security.habitual_fingerprint()


def tearDownModule():
    if security.habitual_fingerprint() != HABITUAL_BEFORE:
        raise AssertionError("The habitual database changed during the C3 smoke suite.")


def repo_previews():
    """Files of the habitual preview cache (listing only)."""
    return sorted(str(path) for path in REPO_PREVIEWS.rglob("*")) if REPO_PREVIEWS.exists() else []


# ---------------------------------------------------------------------- script contract


class ScriptContractTests(unittest.TestCase):
    def tree(self):
        return ast.parse(SCRIPT.read_text(encoding="utf-8"))

    def test_module_level_imports_stay_out_of_the_crm_and_flet(self):
        top = set()
        for node in self.tree().body:
            if isinstance(node, ast.Import):
                top.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                top.add((node.module or "").split(".")[0])
        self.assertEqual(top & {"app", "flet", "fitz", "backend", "database", "frontend", "dotenv", "scripts"},
                         set())
        every = {node.module or "" for node in ast.walk(self.tree()) if isinstance(node, ast.ImportFrom)}
        every |= {alias.name for node in ast.walk(self.tree()) if isinstance(node, ast.Import)
                  for alias in node.names}
        every |= set(smoke.ENTRY_MODULES)
        self.assertFalse(any(name == "app" or name.startswith("app.") for name in every))

    def test_gate_is_only_read_never_assigned_or_patched(self):
        gate = {"EXECUTION_ENABLED", "APPROVED_CONTRACT"}
        reads = []
        for node in ast.walk(self.tree()):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    self.assertNotIn(getattr(target, "attr", getattr(target, "id", None)), gate)
            if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.assertNotIn(getattr(node.slice, "value", None), gate, ast.unparse(node))
            if isinstance(node, ast.Call):
                constants = {arg.value for arg in node.args if isinstance(arg, ast.Constant)}
                constants |= {kw.value.value for kw in node.keywords if isinstance(kw.value, ast.Constant)}
                if constants & gate:
                    # Only the AST reader of the production sources may name the gate (no setattr/patch).
                    self.assertEqual(getattr(node.func, "id", None), "literal_assignments", ast.unparse(node))
                    self.assertIn(getattr(node.args[0], "id", None), ("ARCHIVE_SERVICE", "PERMISSION_SERVICE"))
                    reads.append(node.args[1].value)
        self.assertEqual(sorted(reads), sorted(gate))
        reader = next(node for node in self.tree().body
                      if isinstance(node, ast.FunctionDef) and node.name == "literal_assignments")
        self.assertNotIn("write", ast.unparse(reader))  # parses the source text, never imports nor writes it
        self.assertEqual({name for _module, name, _relative in smoke.WRITE_REDIRECTS} & gate, set())
        self.assertIsNone(smoke.DB_NAME.search("EXECUTION_ENABLED"))

    def test_no_operational_paths_credentials_or_dotenv(self):
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Call):
                func = node.func
                self.assertNotEqual(getattr(func, "id", getattr(func, "attr", None)), "load_dotenv")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertIsNone(re.match(r"^[A-Za-z]:[\\/]", node.value), node.value)
                self.assertNotIn("Desktop", node.value)
                self.assertNotIn("IGNACIO", node.value)

    def test_sandbox_sql_is_the_certified_fixture(self):
        # DV24 CRM + DV25-P3A catalog: the smoke runs on the very contract the suites certify.
        self.assertEqual(smoke.SANDBOX_SQL, dv24.CRM_SQL + p3a.CATALOG_SQL)
        self.assertEqual(len(smoke.DOCUMENTS), smoke.DOC_COUNT)

    def test_viewer_api_is_the_real_crm_components(self):
        api = smoke.viewer_api()
        self.assertIs(api["open"], viewer.open_document_viewer_modal)
        self.assertIs(api["marked_queue"], multidoc.marked_queue)
        self.assertIs(api["view_selected_action"], multidoc.view_selected_action)
        self.assertIs(api["ViewerLinking"], link_dialog.ViewerLinking)
        self.assertIs(api["ViewerNotes"], notes_panel.ViewerNotes)
        self.assertIs(api["PdfToolsToolbarAdapter"], toolbar_adapter.PdfToolsToolbarAdapter)
        self.assertIs(api["archive"], archive)
        source = SCRIPT.read_text(encoding="utf-8")
        # No viewer of its own: no dialog, layout, comparator, notes, link or archive UI is built here.
        for name in ("AlertDialog", "ViewerLayout", "Comparator(", "NotesController", "LinkController",
                     "ArchiveForm", "LinkForm", "copy_inbox_item_to_expedient_box", "execute_archive"):
            self.assertNotIn(name, source)


# ---------------------------------------------------------------------- --check


CHECK_CHILD = r"""
import builtins, importlib.util, io, json, os, sqlite3, sys

cfg = json.loads(sys.argv[1])


def fail(kind, target):
    sys.stderr.write("CHECK_WROTE %s %s\n" % (kind, target))
    sys.stderr.flush()
    os._exit(90)


real_open = builtins.open


def guarded_open(file, mode="r", *args, **kwargs):
    if any(flag in mode for flag in "wxa+"):
        fail("open", file)
    return real_open(file, mode, *args, **kwargs)


builtins.open = io.open = guarded_open
real_os_open = os.open
WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def guarded_os_open(path, flags, *args, **kwargs):
    if flags & WRITE:
        fail("os.open", path)
    return real_os_open(path, flags, *args, **kwargs)


os.open = guarded_os_open
for name in ("mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir", "utime"):
    setattr(os, name, lambda *args, _name=name, **kwargs: fail(_name, args[0] if args else ""))
sqlite3.connect = lambda *args, **kwargs: fail("sqlite3.connect", args[0] if args else "")

spec = importlib.util.spec_from_file_location("dv25_documental_smoke", cfg["script"])
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
smoke.EXPECTED_BRANCH = cfg["branch"]
code = smoke.main(["--check"])
loaded = sorted(n for n in sys.modules if n.split(".")[0] in ("flet", "fitz", "backend", "database", "frontend", "app"))
print("RESULT=" + json.dumps({"code": code, "loaded": loaded}))
"""


class CheckTests(unittest.TestCase):
    def test_gate_is_closed_in_the_code(self):
        self.assertEqual(smoke.gate_state(), (False, None))
        self.assertIs(archive.EXECUTION_ENABLED, False)

    def test_closure_is_fully_classified_and_redirected(self):
        modules, constants, problems = smoke.closure_report()
        self.assertEqual(problems, [])
        kinds = {(module, name): kind for module, name, kind in constants}
        self.assertEqual(kinds[("database.connection", "DB_PATH")], "db-redirect")
        self.assertEqual(kinds[("backend.services.expedient_service", "DB_PATH")], "db-redirect")
        for module, name, _relative in smoke.WRITE_REDIRECTS:
            self.assertEqual(kinds[(module, name)], "write-redirect", (module, name))
        self.assertNotIn("UNREVIEWED", kinds.values())
        # The viewer's lazy imports are followed; app is never reached.
        self.assertIn("frontend.components.document_viewer_archive_dialog", modules)
        self.assertIn("frontend.components.document_viewer_notes_panel", modules)
        self.assertFalse(any(module == "app" or module.startswith("app.") for module in modules))
        # frontend/components/__init__.py runs ``from .app_button import ...``: those modules are scanned.
        self.assertIn("frontend.components.app_button", modules)

    def test_relative_imports_of_a_package_init_are_followed(self):
        with TemporaryDirectory() as temp:
            components = Path(temp) / "frontend" / "components"
            components.mkdir(parents=True)
            (components / "__init__.py").write_text("from .app_helper import x\nfrom . import app_other\n",
                                                    encoding="utf-8")
            (components / "app_helper.py").write_text(
                "from pathlib import Path\nEXPORT_DIR = Path('storage/exports')\n", encoding="utf-8")
            (components / "app_other.py").write_text("", encoding="utf-8")
            (components / "document_viewer_fake.py").write_text("", encoding="utf-8")
            modules, _constants, problems = smoke.closure_report(
                ("frontend.components.document_viewer_fake",), Path(temp))
        self.assertIn("frontend.components.app_helper", modules)
        self.assertIn("frontend.components.app_other", modules)
        self.assertEqual([p for p in problems if p.startswith("MODULE_NOT_FOUND:")], [])
        # Resolving the import correctly still blocks what the resolved module defines.
        self.assertIn("UNREVIEWED_PATH_CONSTANT:frontend.components.app_helper.EXPORT_DIR", problems)

    def test_a_missing_project_module_still_blocks(self):
        with TemporaryDirectory() as temp:
            components = Path(temp) / "frontend" / "components"
            components.mkdir(parents=True)
            (components / "document_viewer_fake.py").write_text("from backend.services import ausente\n",
                                                                encoding="utf-8")
            _modules, _constants, problems = smoke.closure_report(
                ("frontend.components.document_viewer_fake",), Path(temp))
        self.assertIn("MODULE_NOT_FOUND:backend.services", problems)

    def test_unreviewed_constants_app_and_missing_redirects_block(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for folder in ("frontend/components", "backend/services", "app"):
                root.joinpath(*folder.split("/")).mkdir(parents=True)
            (root / "frontend" / "components" / "document_viewer_fake.py").write_text(
                "def later():\n    from backend.services import fake_service\n", encoding="utf-8")
            (root / "backend" / "services" / "fake_service.py").write_text(
                "from pathlib import Path\nimport app.main\n"
                "DB_PATH = Path(__file__).parent / 'x.db'\n"
                "EXPORT_DIR = Path('storage/exports')\n"
                "MESSAGE_PATH = 'texto sin ruta'\n"
                "def lazy():\n    from backend.services import never_followed\n", encoding="utf-8")
            (root / "app" / "main.py").write_text("", encoding="utf-8")
            modules, constants, problems = smoke.closure_report(("frontend.components.document_viewer_fake",), root)
        self.assertIn("backend.services.fake_service", modules)  # lazy import of a viewer component
        self.assertNotIn("backend.services.never_followed", modules)  # lazy import of the backend
        self.assertIn("APP_IN_CLOSURE", problems)
        self.assertIn("UNREVIEWED_PATH_CONSTANT:backend.services.fake_service.EXPORT_DIR", problems)
        self.assertIn(("backend.services.fake_service", "DB_PATH", "db-redirect"), constants)
        self.assertNotIn("MESSAGE_PATH", [name for _module, name, _kind in constants])
        self.assertIn("REQUIRED_DB_PATH_MISSING:database.connection.DB_PATH", problems)
        self.assertTrue(any(problem.startswith("REDIRECT_TARGET_MISSING:") for problem in problems))

    def test_branch_and_head_fail_closed(self):
        head = "a" * 40

        def runner_for(branch_code, branch, head_value=head):
            def run(args, **kwargs):
                if args[1] == "symbolic-ref":
                    return SimpleNamespace(returncode=branch_code, stdout=branch)
                return SimpleNamespace(returncode=0, stdout=head_value)
            return run

        cases = [
            ((0, smoke.EXPECTED_BRANCH), None, []),
            ((0, smoke.EXPECTED_BRANCH), head, []),
            ((0, "main"), None, ["BRANCH_PROTECTED:main"]),
            ((1, ""), None, ["BRANCH_DETACHED"]),
            ((0, "feature/otra"), None, ["BRANCH_UNEXPECTED:feature/otra"]),
            ((0, smoke.EXPECTED_BRANCH), "b" * 40, ["HEAD_MISMATCH"]),
        ]
        for (code, branch), expect, blockers in cases:
            with self.subTest(branch=branch, expect=expect):
                _lines, found = smoke.git_state(expect, runner=runner_for(code, branch))
                self.assertEqual(found, blockers)
        _lines, found = smoke.git_state(None, runner=runner_for(0, smoke.EXPECTED_BRANCH, "no-sha"))
        self.assertIn("HEAD_UNRESOLVED", found)

    def test_check_reads_only_and_never_loads_flet_or_the_crm(self):
        branch = subprocess.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=REPO_ROOT,
                                capture_output=True, text=True).stdout.strip()
        if not branch:
            self.skipTest("Worktree en HEAD desacoplado: --check exige una rama y aquí no hay ninguna.")
        config = {"script": str(SCRIPT), "branch": branch}
        result = subprocess.run([sys.executable, "-B", "-c", CHECK_CHILD, json.dumps(config)], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=600)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        answer = json.loads(next(line for line in result.stdout.splitlines()
                                 if line.startswith("RESULT="))[len("RESULT="):])
        self.assertEqual(answer, {"code": 0, "loaded": []}, output)
        for line in ("CHECK=PASS", "FLET_LAUNCHED=NO", "WRITES=NONE",
                     "GATE=EXECUTION_ENABLED=False APPROVED_CONTRACT=None"):
            self.assertIn(line, result.stdout.splitlines(), output)
        self.assertNotIn("BLOCKER=", result.stdout)


# ---------------------------------------------------------------------- guards


class GuardTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.addCleanup(gc.collect)
        self.root = Path(temp.name).resolve()
        self.guards = smoke.Guards(self.root)

    def test_predicates_fail_closed(self):
        g = self.guards
        self.assertFalse(g.db_allowed(smoke.HABITUAL_DB))
        self.assertFalse(g.db_allowed(str(smoke.HABITUAL_DB)))
        self.assertFalse(g.db_allowed(smoke.HABITUAL_DB.as_uri() + "?mode=ro", uri=True))
        self.assertFalse(g.db_allowed(os.fsencode(smoke.HABITUAL_DB)))
        self.assertFalse(g.db_allowed("relativa.db"))  # resolved against the repository cwd
        self.assertTrue(g.db_allowed(":memory:"))
        self.assertTrue(g.db_allowed("file:memdb?mode=memory&cache=shared", uri=True))
        self.assertTrue(g.db_allowed(self.root / "crm.db"))
        self.assertFalse(g.write_allowed(REPO_ROOT / "data" / "document_inbox" / "x.pdf"))
        self.assertFalse(g.write_allowed(self.root.parent / "fuera.txt"))
        self.assertTrue(g.write_allowed(self.root / "previews" / "x.png"))
        for address in (("203.0.113.9", 443), ("box.com", 443), ("10.0.0.1", 445), (b"192.0.2.1", 80)):
            with self.subTest(address=address):
                self.assertFalse(g.host_allowed(address))
        for address in (("127.0.0.1", 8550), ("::1", 8550), ("localhost", 0), ("0.0.0.0", 0)):
            with self.subTest(address=address):
                self.assertTrue(g.host_allowed(address))
        self.assertFalse(g.exec_allowed(["explorer.exe", "x.pdf"]))
        self.assertFalse(g.exec_allowed([sys.executable, "-c", "pass"]))
        self.assertEqual(smoke.dry_guard_problems(self.root / "nuevo"), [])

    def test_installed_guards_refuse_outside_the_sandbox_and_restore(self):
        originals = (sqlite3.connect, open, os.open, os.mkdir, subprocess.Popen, socket.socket.connect,
                     socket.getaddrinfo)
        probe = REPO_ROOT / "data" / f"dv25_smoke_probe_{os.getpid()}.txt"
        folder = REPO_ROOT / f"dv25_smoke_probe_{os.getpid()}"
        self.guards.install()
        try:
            refused = [
                lambda: sqlite3.connect(str(smoke.HABITUAL_DB)),
                lambda: sqlite3.connect(smoke.HABITUAL_DB.as_uri() + "?mode=ro", uri=True),
                lambda: open(probe, "w"),
                lambda: os.open(str(probe), os.O_CREAT | os.O_WRONLY),
                lambda: os.mkdir(folder),
                lambda: subprocess.Popen([sys.executable, "-c", "pass"]),
                lambda: socket.getaddrinfo("box.com", 443),
            ]
            for index, action in enumerate(refused):
                with self.subTest(index=index), self.assertRaises(smoke.SandboxViolation):
                    action()
            sock = socket.socket()
            try:
                with self.assertRaises(smoke.SandboxViolation):
                    sock.connect(("203.0.113.9", 9))  # refused before any packet is sent
            finally:
                sock.close()
            if hasattr(os, "startfile"):
                with self.assertRaises(smoke.SandboxViolation):
                    os.startfile(str(self.root))
            # Inside the sandbox everything works; reading outside stays possible.
            with closing(sqlite3.connect(self.root / "crm.db")) as conn:
                conn.execute("CREATE TABLE t (x)")
            (self.root / "sub").mkdir()
            (self.root / "sub" / "a.txt").write_text("ok", encoding="utf-8")
            self.assertIn("Smoke visual aislado", SCRIPT.read_text(encoding="utf-8"))
        finally:
            self.guards.uninstall()
        self.assertEqual((sqlite3.connect, open, os.open, os.mkdir, subprocess.Popen, socket.socket.connect,
                          socket.getaddrinfo), originals)
        self.assertFalse(probe.exists())
        self.assertFalse(folder.exists())
        kinds = {kind for kind, _target in self.guards.violations}
        self.assertLessEqual({"sqlite3.connect", "open", "os.open", "os.mkdir", "subprocess",
                              "socket.getaddrinfo", "socket.connect"}, kinds)
        self.assertIn(str(self.root / "crm.db"), self.guards.connections)
        self.assertEqual(self.guards.ddl, [])  # DDL is only recorded once navigation starts


# ---------------------------------------------------------------------- sandbox + real viewer


class SandboxViewerTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # ``with get_connection()`` never closes; free the handles before removing the directory.
        self.addCleanup(gc.collect)
        self.root = Path(temp.name).resolve()
        preference = patch.dict(viewer._TOOLS_PREFERENCE, {"collapsed": False})
        preference.start()
        self.addCleanup(preference.stop)
        self.previews_before = repo_previews()
        self.guards = smoke.Guards(self.root)
        self.guards.install()
        self.addCleanup(self.guards.uninstall)
        self.context, saved = smoke.prepare_runtime(self.root, self.guards)
        self.addCleanup(smoke.restore, saved)
        self.page = SimpleNamespace(overlay=[], update=Mock(), width=1366, height=768)
        self.harness = smoke.SmokeHarness(self.page, self.context, self.guards, run=lambda work: work(),
                                          near_window=0)
        self.harness.control()
        self.schema_before = smoke.schema_snapshot(self.context.db)
        # Spy (real code runs): attributes any navigation DDL to the Bandeja schema helper.
        spy = patch.object(inbox_service, "ensure_document_inbox_schema",
                           wraps=inbox_service.ensure_document_inbox_schema)
        self.ensure_schema = spy.start()
        self.addCleanup(spy.stop)
        self.guards.navigation = True
        self.box_before = self.box_tree()
        self.rows_before = self.rows()

    def tearDown(self):
        dialog = self.harness.dialog
        if dialog is not None and viewer.viewer_layout(dialog) is not None:
            self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.guards.violations, [])
        # Opening the viewer loads the notes activity: get_inbox_events() runs the idempotent
        # CREATE ... IF NOT EXISTS of ensure_document_inbox_schema() (existing behaviour, not DV25).
        # Only that DDL is tolerated while navigating, and the schema must not change.
        self.assertLessEqual(set(self.guards.ddl), smoke.INBOX_SCHEMA_DDL, self.guards.ddl)
        if self.guards.ddl:
            self.assertTrue(self.ensure_schema.called)
        self.assertEqual(smoke.schema_snapshot(self.context.db), self.schema_before)
        outside = [target for target in self.guards.connections
                   if target != ":memory:" and not smoke._inside(target, self.root)]
        self.assertEqual(outside, [])
        self.assertEqual(self.box_tree(), self.box_before)
        self.assertEqual(self.rows(), self.rows_before)
        self.assertEqual(repo_previews(), self.previews_before)

    # ------------------------------------------------------------------ helpers

    def box_tree(self):
        base = self.context.box
        return sorted((path.relative_to(base).as_posix(),
                       hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
                      for path in base.rglob("*"))

    def rows(self):
        with closing(sqlite3.connect(self.context.db)) as conn:
            return conn.execute("SELECT id, status, client_id, expedient_id, copied_to_box_path, "
                                "linked_document_path FROM document_inbox_items ORDER BY id").fetchall()

    @staticmethod
    def labels(dialog):
        return [viewer.viewer_action_label(button) for button in viewer.viewer_action_buttons(dialog)]

    def button(self, dialog, label):
        return next(b for b in viewer.viewer_action_buttons(dialog) if viewer.viewer_action_label(b) == label)

    # ------------------------------------------------------------------ tests

    def test_sandbox_holds_ten_synthetic_pdfs_and_every_path_is_redirected(self):
        items = self.context.items
        self.assertEqual([item["id"] for item in items], list(range(1, 11)))
        originals = self.root / "bandeja" / "originals"
        for item in items:
            path = Path(item["path"])
            self.assertEqual(path.parent, originals)
            with fitz.open(path) as document:
                self.assertGreaterEqual(document.page_count, 2)
                self.assertIn("SINTETICO", document[0].get_text())
        self.assertEqual(smoke.effective_path_problems(self.root, self.context.db), [])
        self.assertEqual(Path(connection.DB_PATH), self.context.db)
        self.assertEqual(Path(expedient_service.DB_PATH), self.context.db)
        self.assertTrue(smoke._inside(viewer_service.PREVIEW_DIR, self.root))
        with closing(sqlite3.connect(self.context.db)) as conn:
            roots = [row[0] for row in conn.execute(
                "SELECT box_folder_path FROM expedientes WHERE box_folder_path IS NOT NULL")]
            digests = dict(conn.execute("SELECT id, sha256 FROM document_inbox_items"))
        self.assertEqual(len(roots), 2)
        self.assertTrue(all(smoke._inside(root, self.context.box) for root in roots))
        for item in items:
            self.assertEqual(digests[item["id"]], hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest())

    def test_two_and_four_marked_documents_open_the_real_viewer(self):
        for count in (2, 4):
            with self.subTest(count=count):
                self.harness.mark(count)
                self.assertEqual([entry["inbox_item_id"] for entry in self.harness.queue()],
                                 list(range(1, count + 1)))
                dialog = self.harness.open_selected()
                self.assertIsInstance(dialog, ft.AlertDialog)
                layout = viewer.viewer_layout(dialog)
                self.assertIsInstance(layout, viewer.ViewerLayout)
                self.assertEqual(viewer.viewer_active_document(dialog).path, self.context.items[0]["path"])
                self.assertIsNotNone(layout.notes)
                self.assertIsNotNone(layout.links)
                # Comparator with one tile per marked document, then back to a single document.
                self.button(dialog, "Comparador 4").on_click(None)
                layout = viewer.viewer_layout(dialog)
                self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
                self.assertEqual(len(layout.tiles), count)
                self.button(dialog, "Documento único").on_click(None)
                self.assertEqual(viewer.viewer_layout(dialog).mode, multidoc.MODE_SINGLE)
                # Zoom and fold keep the document.
                zoom = viewer.viewer_layout(dialog).zoom_label.value
                self.button(dialog, "Zoom +").on_click(None)
                self.assertNotEqual(viewer.viewer_layout(dialog).zoom_label.value, zoom)
                layout = viewer.viewer_layout(dialog)
                folded = layout.tools_collapsed  # session preference: the previous subtest may have folded
                self.assertIsNotNone(layout.tools_toggle)
                layout.tools_toggle.on_click(None)
                self.assertIs(viewer.viewer_layout(dialog).tools_collapsed, not folded)
                self.assertEqual(viewer.viewer_active_document(dialog).path, self.context.items[0]["path"])
                self.button(dialog, "Cerrar").on_click(None)
                self.assertIsNone(viewer.viewer_layout(dialog))

    def test_pdf_tools_are_shown_without_handlers(self):
        self.harness.mark(1)
        dialog = self.harness.open_selected()
        tools = [b for b in viewer.viewer_action_buttons(dialog)
                 if getattr(b, "data", None) in {op for op, _ in toolbar_adapter.PDF_ACTIONS}]
        self.assertEqual(len(tools), len(toolbar_adapter.PDF_ACTIONS))
        self.assertTrue(all(button.disabled for button in tools))

    def assert_p3a_preview(self, form, inbox_ids):
        self.assertIsInstance(form, link_dialog.LinkForm)
        self.assertEqual([request["inbox_item_id"] for request in form.requests], inbox_ids)
        self.assertEqual(form.client_id, 7)  # current client preselected; the expediente is chosen
        dv24.ViewerBase.pick(form.expedient_select, 42)
        # P3A preview of the simulated Box root: one projected row per form document, nothing reserved.
        self.assertIsNotNone(form.filing)
        self.assertEqual([row.inbox_item_id for row in form.preview], inbox_ids)
        self.assertTrue(any(control.data == "filing-preview" for control in form.filing_column.controls))
        self.assertIn(filing_service.PREVIEW_ONLY, dv24.ViewerBase.texts(form.dialog))
        self.assertTrue(form.archive_button.disabled)  # DV28-FIX2: never enabled without confirmation
        self.assertEqual(form.archive_button.on_click, form.submit_and_archive)
        form.close()  # never confirmed: no link, no copy (tearDown: Box tree and rows unchanged)

    def test_link_dialog_shows_the_p3a_preview_with_its_archive_disabled(self):
        # "Vincular a expediente" links the active document only (DV24 open_active), whatever is marked.
        self.harness.mark(2)
        dialog = self.harness.open_selected()
        self.assertNotIn("Vincular seleccionados", self.labels(dialog))
        self.button(dialog, "Vincular a expediente").on_click(None)
        self.assert_p3a_preview(self.page.overlay[-1].data, [1])

    def test_link_selected_shows_the_p3a_preview_of_every_checked_tile(self):
        # "Vincular seleccionados" (DV24 open_selected): comparator tiles checked, ordered by index.
        self.harness.mark(2)
        dialog = self.harness.open_selected()
        self.button(dialog, "Comparador 4").on_click(None)
        self.assertTrue(self.button(dialog, "Vincular seleccionados").disabled)
        for tile in (1, 0):
            checkbox = viewer.viewer_layout(dialog).tiles[tile].checkbox
            checkbox.on_change(SimpleNamespace(control=SimpleNamespace(value=True)))
        self.assertEqual(viewer.viewer_layout(dialog).links.counter_text.value, "2 seleccionados")
        button = self.button(dialog, "Vincular seleccionados")
        self.assertFalse(button.disabled)
        button.on_click(None)
        self.assert_p3a_preview(self.page.overlay[-1].data, [1, 2])

    def test_archive_review_stays_closed_and_writes_nothing(self):
        self.harness.mark(1)
        dialog = self.harness.open_selected()
        button = self.button(dialog, "Archivar en Box")
        self.assertFalse(button.disabled)
        button.on_click(None)
        form = self.page.overlay[-1].data
        self.assertIsInstance(form, archive_dialog.ArchiveForm)
        self.assertIn(archive.EXECUTION_DISABLED, dv24.ViewerBase.texts(form.dialog))
        self.assertTrue(form.submit_button.disabled)
        self.assertIsNone(form.submit())
        form.close()

    def test_without_marks_nothing_opens(self):
        self.harness.mark(0)
        self.assertIsNone(self.harness.open_selected())
        self.assertEqual(self.page.overlay, [])
        self.assertTrue(self.harness.status.value)


if __name__ == "__main__":
    unittest.main()
