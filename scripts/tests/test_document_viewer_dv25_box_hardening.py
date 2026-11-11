"""WO-DV25-P3B1: governed Bandeja -> Box copy (COPY -> VERIFY -> REGISTER), backend only.

Everything lives in a TemporaryDirectory: a synthetic SQLite CRM (``connection.DB_PATH``
redirected and asserted on every connection), a synthetic Bandeja (``INBOX_*`` redirected)
and a synthetic Box tree. ``guard`` makes any delete, move, rename, replace, symlink or
shutil copy fail the test, and any write (open for writing, mkdir) outside the sandbox
too. The pre-existing Box files and every Bandeja original are compared byte for byte in
tearDown, and the habitual database file must not change. No real Box is ever reached.
"""
import ast
import builtins
import gc
import hashlib
import inspect
import io
import json
import os
import shutil
import sqlite3
import stat
import threading
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.services import document_inbox_service as inbox
from backend.services import document_viewer_filing_plan_service as filing
from database import connection


REPO_ROOT = Path(__file__).resolve().parents[2]
INBOX_SERVICE = REPO_ROOT / "backend" / "services" / "document_inbox_service.py"
FILING = REPO_ROOT / "backend" / "services" / "document_viewer_filing_plan_service.py"
INBOX_VIEW = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"
REAL_DB = Path(connection.__file__).resolve().with_name("quesada.db")

CRM_SQL = """
CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT, activo INTEGER DEFAULT 1);
INSERT INTO clientes VALUES (7, 'Cliente Siete', 1), (8, 'Cliente Ocho', 1);
CREATE TABLE expedientes (
    id INTEGER PRIMARY KEY, cliente_id INTEGER, numero_expediente TEXT, activo INTEGER DEFAULT 1,
    tipo_expediente_id INTEGER, subtipo_expediente_id INTEGER, box_folder_path TEXT);
INSERT INTO expedientes (id, cliente_id, numero_expediente, tipo_expediente_id, subtipo_expediente_id)
VALUES (42, 7, 'EXP-42', 1, 10), (43, 7, 'EXP-43', 1, 10), (50, 8, 'EXP-50', 2, NULL);
CREATE TABLE config_tipos_expediente (id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT);
CREATE TABLE config_subtipos_expediente (
    id INTEGER PRIMARY KEY, tipo_expediente_id INTEGER, codigo TEXT, nombre TEXT);
CREATE TABLE config_documentos_catalogo (
    id INTEGER PRIMARY KEY, codigo TEXT NOT NULL UNIQUE, nombre TEXT, descripcion TEXT,
    categoria TEXT, activo INTEGER DEFAULT 1);
CREATE TABLE config_nomenclaturas_catalogo (
    id INTEGER PRIMARY KEY, tipo_expediente_id INTEGER, subtipo_expediente_id INTEGER,
    documento_catalogo_id INTEGER, rol_documental TEXT, prioridad INTEGER DEFAULT 100,
    activo INTEGER DEFAULT 1);
CREATE TABLE config_nomenclaturas_procedimentales (
    id INTEGER PRIMARY KEY AUTOINCREMENT, documento_catalogo_id INTEGER NOT NULL,
    patron_nombre TEXT NOT NULL, extension_permitida TEXT NOT NULL DEFAULT 'pdf,jpg,jpeg,png',
    prioridad INTEGER NOT NULL DEFAULT 100, activo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT, updated_at TEXT);
INSERT INTO config_tipos_expediente VALUES (1, 'ARRAIGO', 'Arraigo'), (2, 'NACIONALIDAD', 'Nacionalidad');
INSERT INTO config_subtipos_expediente VALUES (10, 1, 'SOCIAL', 'Social');
INSERT INTO config_documentos_catalogo (id, codigo, nombre, categoria, activo) VALUES
    (100, 'PASAPORTE', 'PASAPORTE', 'IDENTIDAD', 1),
    (102, 'NIE_TIE', 'NIE/TIE', 'IDENTIDAD', 1),
    (103, 'CERT_NACIMIENTO', 'CERTIFICADO DE NACIMIENTO', 'REGISTRO', 1);
INSERT INTO config_nomenclaturas_catalogo
    (tipo_expediente_id, subtipo_expediente_id, documento_catalogo_id, rol_documental, prioridad) VALUES
    (1, NULL, 100, 'SOLICITANTE', 10), (1, 10, 102, NULL, 20), (2, NULL, 103, NULL, 10);
"""
EXISTING = "01 IDENTIDAD/PASAPORTE SOLICITANTE.pdf"
ITEM_COLUMNS = ("status", "client_id", "expedient_id", "stored_path", "stored_filename",
                "original_filename", "linked_document_path", "copied_to_box_path", "copied_to_box_at",
                "sha256")
# Operations that would delete, move, rename or overwrite: never allowed, not even in the sandbox.
FORBIDDEN_OS = ("remove", "unlink", "rename", "renames", "replace", "rmdir", "removedirs", "symlink", "link")
FORBIDDEN_SHUTIL = ("move", "rmtree", "copy", "copy2", "copyfile", "copytree")
NEW_HELPERS = {
    "copy_inbox_item_to_expedient_box", "_copy_inbox_item_to_box", "_box_destination_folder",
    "_create_box_copy", "_stream_into", "_verify_box_copy", "_register_box_copy",
    "_record_box_copy_failure", "_authorized_box_root", "_verified_inbox_source", "_identical_box_file",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FailingWriter:
    """File handle that fails like a full disk once ``limit`` bytes were written."""

    def __init__(self, handle, limit):
        self.handle, self.limit, self.written = handle, limit, 0

    def write(self, data):
        if self.written + len(data) > self.limit:
            raise OSError(28, "No space left on device (simulado)")
        self.written += len(data)
        return self.handle.write(data)

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.handle.close()
        return False


class CountingWriter:
    """File handle proxy that records the size of every write (streaming evidence)."""

    def __init__(self, handle):
        self.handle, self.sizes = handle, []

    def write(self, data):
        self.sizes.append(len(data))
        return self.handle.write(data)

    def __getattr__(self, name):
        return getattr(self.handle, name)


class BoxCopyBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # ``with get_connection() as conn`` commits but never closes; free the handles before
        # the directory is removed on Windows (cleanups run LIFO).
        self.addCleanup(gc.collect)
        self.root = Path(temp.name).resolve()
        self.real_db_before = self.real_db_state()

        self.db = self.root / "crm.db"
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(CRM_SQL)
            conn.commit()
        self.patch(connection, "DB_PATH", str(self.db))
        self.db_calls = 0
        real_get, real_readonly = connection.get_connection, connection.get_readonly_connection

        def checked_get():
            self.assertEqual(Path(connection.DB_PATH), self.db)
            self.db_calls += 1
            return real_get()

        def checked_readonly(db_path=None, timeout=30):
            self.assertEqual(Path(connection.DB_PATH if db_path is None else db_path), self.db)
            self.db_calls += 1
            return real_readonly(db_path, timeout)

        self.patch(connection, "get_connection", checked_get)
        self.patch(inbox, "get_connection", checked_get)
        self.patch(connection, "get_readonly_connection", checked_readonly)

        bandeja = self.root / "bandeja"
        self.patch(inbox, "INBOX_ROOT", bandeja)
        self.patch(inbox, "INBOX_ORIGINALS", bandeja / "originals")
        self.patch(inbox, "INBOX_PROCESSED", bandeja / "processed")
        self.patch(inbox, "INBOX_REJECTED", bandeja / "rejected")
        self.patch(inbox, "INBOX_TMP", bandeja / "tmp")
        inbox.ensure_document_inbox_schema()
        self.originals = bandeja / "originals"

        self.box = self.root / "box" / "EXP-42"
        self.box50 = self.root / "box" / "EXP-50"
        for folder in ("01 IDENTIDAD", "02 LABORAL/Contratos"):
            (self.box / folder).mkdir(parents=True)
        self.box50.mkdir(parents=True)
        (self.box / EXISTING).write_bytes(b"%PDF existente en Box")
        (self.box / "Nota previa.txt").write_text("previa", encoding="utf-8")
        self.outside = self.root / "fuera"
        (self.outside / "secreta").mkdir(parents=True)
        self.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = 42", (str(self.box),))
        self.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = 50", (str(self.box50),))

        self.next_id = 0
        self.sources = {}
        self.mutable_sources = set()
        self.write_limit = None
        self.violations = []
        self.box_write_modes = []
        self.protect_box()
        self.guard()

    def tearDown(self):
        self.assertEqual(self.violations, [])
        for path, (data, mtime) in self.protected.items():
            self.assertTrue(path.is_file(), path)
            self.assertEqual(path.read_bytes(), data, path)
            self.assertEqual(path.stat().st_mtime_ns, mtime, path)
        for item_id, (path, data) in self.sources.items():
            if item_id not in self.mutable_sources:
                self.assertEqual(path.read_bytes(), data, path)  # the original is never renamed nor changed
        self.assertEqual(sorted(p.name for p in self.outside.rglob("*")), ["secreta"])
        self.assertLessEqual(set(self.box_write_modes), {"xb"})  # the service only creates new files
        self.assertEqual(self.real_db_state(), self.real_db_before)

    # ------------------------------------------------------------------ sandbox

    def patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    @staticmethod
    def real_db_state():
        return REAL_DB.stat().st_mtime_ns if REAL_DB.exists() else None

    def inside_sandbox(self, target):
        resolved = Path(os.fsdecode(os.fspath(target))).resolve()
        return resolved == self.root or self.root in resolved.parents

    def guard(self):
        self.real = {name: getattr(os, name) for name in FORBIDDEN_OS}

        def forbidden(name):
            def wrapper(*args, **kwargs):
                self.violations.append((name, str(args[0]) if args else ""))
                raise AssertionError(f"forbidden {name}")
            return wrapper

        for name in FORBIDDEN_OS:
            self.patch(os, name, forbidden(f"os.{name}"))
        for name in FORBIDDEN_SHUTIL:
            self.patch(shutil, name, forbidden(f"shutil.{name}"))

        real_mkdir, real_open = os.mkdir, io.open
        self.real_open = real_open

        def guarded_mkdir(path, *args, **kwargs):
            if not self.inside_sandbox(path):
                self.violations.append(("mkdir", str(path)))
                raise AssertionError(f"mkdir outside sandbox: {path}")
            return real_mkdir(path, *args, **kwargs)

        def guarded_open(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wxa+"):
                if not self.inside_sandbox(file):
                    self.violations.append(("open", str(file)))
                    raise AssertionError(f"write outside sandbox: {file}")
                if self.root / "box" in Path(os.fsdecode(os.fspath(file))).resolve().parents:
                    self.box_write_modes.append(mode)
                    handle = real_open(file, mode, *args, **kwargs)
                    return FailingWriter(handle, self.write_limit) if self.write_limit is not None else handle
            return real_open(file, mode, *args, **kwargs)

        self.patch(os, "mkdir", guarded_mkdir)
        self.patch(io, "open", guarded_open)
        self.patch(builtins, "open", guarded_open)

    def seed(self, path, data):
        """Test-side Box fixture written behind the guard (not counted as a service write)."""
        with self.real_open(path, "wb") as handle:
            handle.write(data)

    def protect_box(self):
        self.protected = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in self.root.joinpath("box").rglob("*") if path.is_file()}

    def make_dir_link(self, target, link):
        """Directory symlink if allowed, otherwise an NTFS junction (no privilege needed)."""
        try:
            self.real["symlink"](target, link, target_is_directory=True)
            kind = "symlink"
        except (OSError, NotImplementedError):
            if os.name != "nt":
                raise
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            kind = "junction"
        self.addCleanup(self.real["rmdir"] if os.name == "nt" else self.real["unlink"], link)
        return kind

    def tree(self):
        """(relative path, kind, bytes) of box/ and fuera/; links are listed, never followed."""
        entries = []
        for base in (self.root / "box", self.outside):
            pending = [base]
            while pending:
                folder = pending.pop()
                for child in sorted(folder.iterdir()):
                    relative = child.relative_to(self.root).as_posix()
                    if child.is_symlink() or child.resolve() != child:
                        entries.append((relative, "link", None))
                    elif child.is_dir():
                        entries.append((relative, "dir", None))
                        pending.append(child)
                    else:
                        entries.append((relative, "file", child.read_bytes()))
        return sorted(entries, key=lambda entry: entry[0])

    # ------------------------------------------------------------------ synthetic CRM

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params)]

    def execute(self, sql, params=()):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute(sql, params)
            conn.commit()

    def add_item(self, content=None, name="Pasaporte.pdf", *, client_id=7, expedient_id=42,
                 status="linked", sha256=None, stored_path=None):
        self.next_id += 1
        item_id = self.next_id
        content = f"%PDF-1.4 documento sintetico {item_id}".encode() if content is None else content
        if stored_path is None:
            path = self.originals / f"{item_id:04d}_{name}"
            path.write_bytes(content)
            self.sources[item_id] = (path, content)
        else:
            path = Path(stored_path)
        self.execute(
            "INSERT INTO document_inbox_items (id, original_filename, stored_filename, stored_path, "
            "file_ext, size_bytes, sha256, status, client_id, expedient_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, name, path.name, str(path), path.suffix.lstrip("."), len(content),
             sha(content) if sha256 is None else sha256, status, client_id, expedient_id,
             "2026-11-01 10:00:00"))
        return item_id

    def row(self, item_id):
        return self.query("SELECT * FROM document_inbox_items WHERE id = ?", (item_id,))[0]

    def item_state(self, item_id):
        row = self.row(item_id)
        return {column: row[column] for column in ITEM_COLUMNS}

    def events(self, item_id, event_type=None):
        rows = self.query("SELECT event_type, metadata_json FROM document_inbox_events "
                          "WHERE item_id = ? ORDER BY id", (item_id,))
        return [dict(row, metadata=json.loads(row["metadata_json"] or "{}")) for row in rows
                if event_type is None or row["event_type"] == event_type]

    def copy(self, item_id, expedient_id=42, **kwargs):
        return inbox.copy_inbox_item_to_expedient_box(item_id, expedient_id=expedient_id, **kwargs)

    def assert_refused(self, item_id, error=inbox.BoxCopyRejected, **kwargs):
        """The call fails before creating any file; item, events and Box tree stay put."""
        state, events, tree = self.item_state(item_id), self.events(item_id), self.tree()
        with self.assertRaises(error) as caught:
            self.copy(item_id, **kwargs)
        self.assertNotIsInstance(caught.exception, inbox.BoxCopyIncomplete)
        self.assertEqual(self.item_state(item_id), state)
        self.assertEqual(self.events(item_id), events)
        self.assertEqual(self.tree(), tree)
        return caught.exception

    def assert_registered(self, item_id, result, dest):
        state = self.item_state(item_id)
        self.assertEqual(state["status"], "copied_to_box")
        self.assertEqual(state["copied_to_box_path"], str(dest))
        self.assertEqual(state["linked_document_path"], str(dest))
        self.assertEqual(result["copied_to_box_path"], str(dest))
        self.assertEqual(dest.read_bytes(), self.sources[item_id][1])


class SandboxTests(BoxCopyBase):
    def test_guard_and_database_redirection_are_active(self):
        with self.assertRaises(AssertionError):
            os.unlink(self.box / EXISTING)
        with self.assertRaises(AssertionError):
            shutil.copy2(self.box / EXISTING, self.box / "x.pdf")
        with self.assertRaises(AssertionError):
            (self.root.parent / f"fuera_de_sandbox_{os.getpid()}.txt").write_bytes(b"x")
        self.assertEqual(len(self.violations), 3)
        self.violations.clear()
        item = self.add_item()
        calls = self.db_calls
        self.copy(item)
        self.assertGreater(self.db_calls, calls)
        self.assertEqual(Path(connection.DB_PATH), self.db)
        for row in self.query("SELECT box_folder_path FROM expedientes WHERE box_folder_path IS NOT NULL"):
            self.assertTrue(self.inside_sandbox(row["box_folder_path"]))

    def test_new_code_has_no_delete_move_rename_or_overwrite_primitive(self):
        tree = ast.parse(INBOX_SERVICE.read_text(encoding="utf-8"))
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertTrue(NEW_HELPERS <= set(functions))
        banned = {"copy2", "copyfile", "copy", "move", "unlink", "remove", "rename", "replace", "rmtree",
                  "rmdir", "makedirs", "_unique_destination", "write_bytes", "write_text", "touch"}
        for name in NEW_HELPERS:
            calls = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                     for node in ast.walk(functions[name]) if isinstance(node, ast.Call)}
            self.assertEqual(calls & banned, set(), name)
            opens = [node for node in ast.walk(functions[name]) if isinstance(node, ast.Call)
                     and getattr(node.func, "attr", None) == "open"]
            for node in opens:
                self.assertIn(node.args[0].value, ("rb", "xb"), name)
        # P3A stays a read-only planner: it never references the copy.
        text = FILING.read_text(encoding="utf-8")
        self.assertNotIn("copy_inbox_item_to_expedient_box", text)
        self.assertNotIn("copy_document_inbox_batch_to_expedient_box", text)


class DestinationFolderTests(BoxCopyBase):
    def test_existing_subfolder_inside_root(self):
        item = self.add_item()
        result = self.copy(item, subfolder="02 LABORAL/Contratos")
        dest = self.box / "02 LABORAL" / "Contratos" / "Pasaporte.pdf"
        self.assert_registered(item, result, dest)
        self.assertEqual(result["box_copy"]["created_folders"], [])
        self.assertEqual(result["box_copy"]["subfolder"], "02 LABORAL/Contratos")

    def test_legacy_spellings_of_root_and_trailing_separators(self):
        for subfolder, expected in (("", self.box), (".", self.box), ("  ", self.box),
                                    ("01 IDENTIDAD/", self.box / "01 IDENTIDAD"),
                                    ("02 LABORAL\\Contratos\\", self.box / "02 LABORAL" / "Contratos")):
            with self.subTest(subfolder=subfolder):
                item = self.add_item(name=f"Doc{self.next_id + 1}.pdf")
                result = self.copy(item, subfolder=subfolder)
                self.assert_registered(item, result, expected / f"Doc{item}.pdf")

    def test_missing_subfolders_are_created_one_by_one_inside_root(self):
        item = self.add_item()
        result = self.copy(item, subfolder="03 NUEVA/Requerimientos")
        dest = self.box / "03 NUEVA" / "Requerimientos" / "Pasaporte.pdf"
        self.assert_registered(item, result, dest)
        self.assertEqual(result["box_copy"]["created_folders"], ["03 NUEVA", "03 NUEVA/Requerimientos"])

    def test_hostile_subfolders_are_refused_before_any_write(self):
        item = self.add_item()
        hostile = [
            "..", "../fuera", "01 IDENTIDAD/../../fuera", "./01 IDENTIDAD", "a/./b", "a//b", "/", "\\",
            "/fuera", "\\fuera", str(self.outside), "C:/fuera", "C:fuera", "c:\\fuera", "//servidor/box",
            "\\\\servidor\\box\\EXP", "\\\\?\\C:\\fuera", "CON", "01 IDENTIDAD/NUL", "aux.txt", "COM1",
            "LPT1/x", "carpeta.", "a /b", "a/ b", "a:b", "a*b", "a?b", "a<b", 'a"b', "a|b", "a\x00b",
            "a\nb", "a\tb", "/".join(["a"] * 9), "x" * 201,
        ]
        for subfolder in hostile:
            with self.subTest(subfolder=subfolder):
                self.assert_refused(item, subfolder=subfolder)
        self.assertEqual(self.item_state(item)["status"], "linked")

    def test_link_or_junction_inside_root_is_refused_and_never_followed(self):
        kind = self.make_dir_link(self.outside, self.box / "01 IDENTIDAD" / "salida")
        self.protect_box()
        item = self.add_item()
        for subfolder in ("01 IDENTIDAD/salida", "01 IDENTIDAD/salida/secreta", "01 IDENTIDAD/salida/nueva"):
            with self.subTest(kind=kind, subfolder=subfolder):
                self.assert_refused(item, subfolder=subfolder)
        self.assertFalse((self.outside / "nueva").exists())

    def test_box_root_must_be_configured_local_real_folder(self):
        item = self.add_item()
        (self.root / "un_archivo.txt").write_text("x", encoding="utf-8")
        cases = [
            (str(self.root / "no_existe"), FileNotFoundError),
            (str(self.root / "un_archivo.txt"), FileNotFoundError),
            ("box/EXP-42", inbox.BoxCopyRejected),
            ("\\\\servidor\\box\\EXP-42", inbox.BoxCopyRejected),
            ("//servidor/box/EXP-42", inbox.BoxCopyRejected),
            ("   ", ValueError),
        ]
        for raw, error in cases:
            with self.subTest(raw=raw):
                self.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = 42", (raw,))
                self.assert_refused(item, error=error)
        self.assert_refused(item, error=ValueError, expedient_id=43)   # no Box folder at all
        self.assert_refused(item, error=ValueError, expedient_id=99)   # no such expediente

    def test_box_root_that_is_a_link_or_junction_is_refused(self):
        link = self.root / "box_enlace"
        kind = self.make_dir_link(self.box, link)
        self.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = 42", (str(link),))
        item = self.add_item()
        with self.subTest(kind=kind):
            self.assert_refused(item)

    def test_reparse_points_other_than_cloud_placeholders_are_unsafe(self):
        directory = stat.S_IFDIR
        cases = [
            (SimpleNamespace(st_mode=stat.S_IFLNK), True),
            (SimpleNamespace(st_mode=directory, st_file_attributes=0x400, st_reparse_tag=0xA0000003), True),
            (SimpleNamespace(st_mode=directory, st_file_attributes=0x400, st_reparse_tag=0xA000000C), True),
            (SimpleNamespace(st_mode=directory, st_file_attributes=0x400), True),
            (SimpleNamespace(st_mode=directory, st_file_attributes=0x400, st_reparse_tag=0x9000001A), False),
            (SimpleNamespace(st_mode=directory, st_file_attributes=0x400, st_reparse_tag=0x9000701A), False),
            (SimpleNamespace(st_mode=directory, st_file_attributes=0x10), False),
            (SimpleNamespace(st_mode=directory), False),
        ]
        for st, unsafe in cases:
            with self.subTest(st=st):
                self.assertIs(inbox._reparse_redirects(st), unsafe)


class FilenameTests(BoxCopyBase):
    def test_hostile_names_are_refused(self):
        item = self.add_item()
        hostile = ["../x", "..", "a/b", "a\\b", "C:x", "x:ads", "CON", "con.pdf", "NUL.pdf", "COM1",
                   "LPT9.pdf", "CONIN$", "COM\u00b9.pdf", "nombre.", "nombre.pdf.", "nombre. ", ".oculto",
                   "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b", "a\tb", "a\x00b", "x" * 250,
                   "doc.exe", "doc.docx", "doc.PDFX"]
        for name in hostile:
            with self.subTest(name=name):
                self.assert_refused(item, target_filename=name)

    def test_valid_names_keep_the_real_extension(self):
        for requested, final in (("Contrato", "Contrato.pdf"), ("Contrato firmado.PDF", "Contrato firmado.PDF"),
                                 ("PASAPORTE J. GARCIA", "PASAPORTE J. GARCIA.pdf"),
                                 ("  Consulta  ", "Consulta.pdf")):
            with self.subTest(requested=requested):
                item = self.add_item()
                result = self.copy(item, target_filename=requested)
                self.assert_registered(item, result, self.box / final)
                self.assertEqual(result["box_copy"]["final_filename"], final)

    def test_pure_validators(self):
        self.assertEqual(filing.check_subfolder(" 01 IDENTIDAD/ "), "01 IDENTIDAD")
        self.assertEqual(filing.check_filename("Doc", ".pdf"), "Doc.pdf")
        for name in ("nombre ", " nombre", "a/b", "CON.pdf", "x.exe"):
            with self.subTest(name=name), self.assertRaises(filing.FilingPlanError):
                filing.check_filename(name, ".pdf")
        for extension in ("", "pdf", ".p d f", ".pdf/x", None):
            with self.subTest(extension=extension), self.assertRaises(filing.FilingPlanError):
                filing.check_filename("Doc", extension)
        for value in (None, 3, "../x", "C:/x", "/x"):
            with self.subTest(value=value), self.assertRaises(filing.FilingPlanError):
                filing.check_subfolder(value)

    def test_source_without_valid_extension_is_refused(self):
        item = self.add_item(name="sin_extension")
        self.assert_refused(item)

    def test_nomenclature_from_the_expedient_catalog(self):
        item = self.add_item()
        result = self.copy(item, nomenclature_key="EXPEDIENTE:100:SOLICITANTE")
        self.assert_registered(item, result, self.box / "PASAPORTE SOLICITANTE.pdf")
        trace = result["box_copy"]
        self.assertEqual((trace["nomenclature_code"], trace["rol_documental"]), ("PASAPORTE", "SOLICITANTE"))
        # A catalog name with a separator is sanitized by P3A's safe_stem, never used as a path.
        other = self.add_item()
        result = self.copy(other, nomenclature_key="EXPEDIENTE:102:")
        self.assert_registered(other, result, self.box / "NIE_TIE.pdf")
        # Same proposal as the P3A preview: the existing name projects to _2.
        third = self.add_item()
        result = self.copy(third, subfolder="01 IDENTIDAD", nomenclature_key="EXPEDIENTE:100:SOLICITANTE")
        self.assert_registered(third, result, self.box / "01 IDENTIDAD" / "PASAPORTE SOLICITANTE_2.pdf")
        self.assertEqual(result["box_copy"]["collision_decision"], "renamed")

    def test_unknown_foreign_or_ambiguous_nomenclature_is_refused(self):
        item = self.add_item()
        self.assert_refused(item, nomenclature_key="EXPEDIENTE:999:")
        self.assert_refused(item, nomenclature_key="EXPEDIENTE:103:")  # belongs to expediente 50's family
        self.assert_refused(item, nomenclature_key="EXPEDIENTE:100:SOLICITANTE", target_filename="Otro")

    def test_original_is_never_renamed(self):
        item = self.add_item()
        before = self.item_state(item)
        self.copy(item, target_filename="Nombre canonico")
        after = self.item_state(item)
        for column in ("stored_path", "stored_filename", "original_filename", "sha256"):
            self.assertEqual(after[column], before[column])
        self.assertTrue(self.sources[item][0].is_file())


class CollisionTests(BoxCopyBase):
    def test_existing_name_is_never_overwritten(self):
        self.seed(self.box / "Pasaporte.pdf", b"otro documento previo")
        self.protect_box()
        item = self.add_item()
        result = self.copy(item)
        self.assert_registered(item, result, self.box / "Pasaporte_2.pdf")
        self.assertEqual(result["box_copy"]["collision_decision"], "renamed")

    def test_folder_with_the_candidate_name_is_skipped(self):
        (self.box / "Pasaporte.pdf").mkdir()
        item = self.add_item()
        result = self.copy(item)
        self.assert_registered(item, result, self.box / "Pasaporte_2.pdf")
        self.assertEqual(list((self.box / "Pasaporte.pdf").iterdir()), [])

    def test_identical_file_in_the_series_is_reused_not_duplicated(self):
        item = self.add_item()
        self.seed(self.box / "Pasaporte.pdf", b"distinto")
        self.seed(self.box / "Pasaporte_2.pdf", self.sources[item][1])
        self.protect_box()
        result = self.copy(item)
        self.assert_registered(item, result, self.box / "Pasaporte_2.pdf")
        self.assertEqual(result["box_copy"]["collision_decision"], "reused_identical")
        self.assertFalse((self.box / "Pasaporte_3.pdf").exists())

    def test_exhausted_series_is_refused(self):
        self.patch(inbox, "_BOX_COPY_MAX_CANDIDATES", 3)
        for name in ("Pasaporte.pdf", "Pasaporte_2.pdf", "Pasaporte_3.pdf"):
            self.seed(self.box / name, name.encode())
        self.protect_box()
        self.assert_refused(self.add_item())

    def test_concurrent_copies_with_the_same_name_never_overwrite(self):
        items = [self.add_item() for _ in range(6)]
        barrier, errors, results = threading.Barrier(len(items)), [], {}

        def worker(item_id):
            try:
                barrier.wait(timeout=10)
                results[item_id] = self.copy(item_id, target_filename="Contrato")
            except BaseException as exc:  # reported below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(item_id,)) for item_id in items]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        paths = {Path(results[item_id]["copied_to_box_path"]) for item_id in items}
        expected = {self.box / "Contrato.pdf", *(self.box / f"Contrato_{n}.pdf" for n in range(2, 7))}
        self.assertEqual(paths, expected)
        for item_id in items:
            self.assert_registered(item_id, results[item_id], Path(results[item_id]["copied_to_box_path"]))
        self.assertEqual(set(self.box_write_modes), {"xb"})

    def test_concurrent_copies_of_the_same_item_copy_once(self):
        item = self.add_item()
        barrier, errors, results = threading.Barrier(2), [], []

        def worker():
            try:
                barrier.wait(timeout=10)
                results.append(self.copy(item))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(r["box_copy"]["result"] for r in results), ["already_copied", "copied"])
        self.assertEqual(sorted(p.name for p in self.box.glob("Pasaporte*")), ["Pasaporte.pdf"])
        self.assertEqual(len(self.events(item, "copied_to_box")), 1)


class IntegrityTests(BoxCopyBase):
    def test_trace_of_a_verified_copy(self):
        item = self.add_item()
        result = self.copy(item, subfolder="01 IDENTIDAD")
        dest = self.box / "01 IDENTIDAD" / "Pasaporte.pdf"
        self.assert_registered(item, result, dest)
        [event] = self.events(item, "copied_to_box")
        trace = event["metadata"]
        content = self.sources[item][1]
        self.assertEqual(trace["source_path"], str(self.sources[item][0]))
        self.assertEqual(trace["destination_path"], str(dest))
        self.assertEqual((trace["expedient_id"], trace["client_id"]), (42, 7))
        self.assertEqual(trace["final_filename"], "Pasaporte.pdf")
        self.assertEqual(trace["source_sha256"], sha(content))
        self.assertEqual(trace["destination_sha256"], sha(content))
        self.assertEqual(trace["source_size_bytes"], len(content))
        self.assertEqual(trace["destination_size_bytes"], len(content))
        self.assertEqual((trace["collision_decision"], trace["result"]), ("none", "copied"))
        for key in ("verified_at", "registered_at", "box_root", "subfolder", "created_folders"):
            self.assertIn(key, trace)
        self.assertEqual(self.events(item, "copy_to_box_failed"), [])

    def test_zero_bytes(self):
        item = self.add_item(content=b"")
        result = self.copy(item)
        self.assert_registered(item, result, self.box / "Pasaporte.pdf")
        self.assertEqual(result["box_copy"]["destination_sha256"], sha(b""))

    def test_large_files_are_streamed_and_copied_whole(self):
        for chunk, size in ((inbox._BOX_COPY_CHUNK, 8 * 1024 * 1024 + 123), (4096, 4096 * 3 + 7)):
            with self.subTest(chunk=chunk, size=size), patch.object(inbox, "_BOX_COPY_CHUNK", chunk):
                item = self.add_item(content=os.urandom(size), name=f"Grande{chunk}.pdf")
                reads = []
                real_stream = inbox._stream_into

                def counting(src, handle):
                    proxy = CountingWriter(handle)
                    try:
                        return real_stream(src, proxy)
                    finally:
                        reads.extend(proxy.sizes)

                with patch.object(inbox, "_stream_into", counting):
                    result = self.copy(item)
                self.assert_registered(item, result, self.box / f"Grande{chunk}.pdf")
                self.assertEqual(sum(reads), size)
                self.assertLessEqual(max(reads), chunk)
                self.assertGreater(len(reads), 1)

    def test_write_failure_leaves_a_traced_unregistered_file_and_retry_does_not_reuse_it(self):
        item = self.add_item(content=b"0123456789" * 3)
        before = self.item_state(item)
        self.write_limit = 8
        with patch.object(inbox, "_BOX_COPY_CHUNK", 4), self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item)
        self.write_limit = None
        error = caught.exception
        partial = self.box / "Pasaporte.pdf"
        self.assertEqual((error.stage, error.written_path, error.created), ("write", str(partial), True))
        self.assertEqual(partial.read_bytes(), b"01234567")       # left in place, never deleted
        self.assertEqual(self.item_state(item), before)
        self.assertEqual(self.events(item, "copied_to_box"), [])
        [failure] = self.events(item, "copy_to_box_failed")
        self.assertEqual(failure["metadata"]["result"], "failed_write")
        self.assertEqual(failure["metadata"]["destination_path"], str(partial))
        self.protect_box()   # the partial copy is now a Box file to protect as well
        result = self.copy(item)
        self.assert_registered(item, result, self.box / "Pasaporte_2.pdf")

    def test_flush_failure_never_registers(self):
        item = self.add_item()
        before = self.item_state(item)
        with patch.object(os, "fsync", side_effect=OSError(28, "No space left on device")), \
                self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item)
        self.assertEqual(caught.exception.stage, "write")
        self.assertEqual(self.item_state(item), before)
        self.assertEqual(self.events(item, "copied_to_box"), [])

    def test_verification_failure_never_registers(self):
        item = self.add_item()
        before = self.item_state(item)
        real_sha = inbox._sha256

        def corrupt(path):
            return "0" * 64 if self.box in Path(path).parents else real_sha(path)

        with patch.object(inbox, "_sha256", corrupt), self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item)
        self.assertEqual(caught.exception.stage, "verify")
        self.assertTrue((self.box / "Pasaporte.pdf").is_file())
        self.assertEqual(self.item_state(item), before)
        self.assertEqual(self.events(item, "copied_to_box"), [])
        self.assertEqual(self.events(item, "copy_to_box_failed")[0]["metadata"]["result"], "failed_verify")

    def test_source_changing_during_the_copy_is_detected(self):
        item = self.add_item()
        self.mutable_sources.add(item)
        before = self.item_state(item)
        source = self.sources[item][0]
        real_sha = inbox._sha256

        def then_modify(path):
            digest = real_sha(path)
            if Path(path) == source.resolve():
                with open(source, "ab") as handle:
                    handle.write(b" cambio concurrente")
            return digest

        with patch.object(inbox, "_sha256", then_modify), self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item)
        self.assertEqual(caught.exception.stage, "verify")
        self.assertEqual(self.item_state(item), before)

    def test_source_that_no_longer_matches_its_recorded_hash_is_refused(self):
        self.assert_refused(self.add_item(sha256="f" * 64))

    def test_legacy_item_without_recorded_hash_is_copied(self):
        item = self.add_item(sha256="")
        self.assert_registered(item, self.copy(item), self.box / "Pasaporte.pdf")

    def test_source_must_be_a_bandeja_file(self):
        external = self.root / "descargas" / "externo.pdf"
        external.parent.mkdir()
        external.write_bytes(b"%PDF externo")
        self.assert_refused(self.add_item(stored_path=external))
        self.assert_refused(self.add_item(stored_path=self.box / EXISTING))
        self.assert_refused(self.add_item(stored_path=self.originals / "no_existe.pdf"), error=FileNotFoundError)

    def test_client_of_the_item_must_own_the_expedient(self):
        self.assert_refused(self.add_item(client_id=8))
        item = self.add_item(client_id=None, expedient_id=None, status="pending")
        result = self.copy(item)
        self.assertEqual((result["client_id"], result["expedient_id"]), (7, 42))


class RegistrationTests(BoxCopyBase):
    def failing_event(self, event_type="copied_to_box"):
        real = inbox._record_event

        def record(conn, item_id, kind, message="", metadata=None):
            if event_type in (None, kind):
                raise sqlite3.OperationalError("database is locked (simulado)")
            return real(conn, item_id, kind, message, metadata)
        return record

    def test_registration_failure_is_recoverable_without_a_second_copy(self):
        item = self.add_item()
        before = self.item_state(item)
        with patch.object(inbox, "_record_event", self.failing_event()), \
                self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item)
        dest = self.box / "Pasaporte.pdf"
        error = caught.exception
        self.assertEqual((error.stage, error.written_path, error.created), ("register", str(dest), True))
        self.assertEqual(dest.read_bytes(), self.sources[item][1])  # verified and kept
        self.assertEqual(self.item_state(item), before)            # rolled back: no premature success
        self.assertEqual(self.events(item, "copied_to_box"), [])
        self.assertEqual(self.events(item, "copy_to_box_failed")[0]["metadata"]["result"], "failed_register")

        result = self.copy(item)
        self.assert_registered(item, result, dest)
        self.assertEqual(result["box_copy"]["collision_decision"], "reused_identical")
        self.assertEqual(sorted(p.name for p in self.box.glob("Pasaporte*")), ["Pasaporte.pdf"])
        self.assertEqual(len(self.events(item, "copied_to_box")), 1)

    def test_database_fully_down_after_copy_still_leaves_a_consistent_item(self):
        item = self.add_item()
        before = self.item_state(item)
        with patch.object(inbox, "_record_event", self.failing_event(None)), \
                self.assertRaises(inbox.BoxCopyIncomplete):
            self.copy(item)
        self.assertEqual(self.item_state(item), before)
        self.assertEqual(self.events(item), [])

    def test_registration_never_overwrites_a_concurrent_registration(self):
        item = self.add_item()
        other = str(self.box / "otra copia.pdf")
        real_create = inbox._create_box_copy

        def racing(*args, **kwargs):
            result = real_create(*args, **kwargs)
            self.execute("UPDATE document_inbox_items SET status = 'copied_to_box', copied_to_box_path = ? "
                         "WHERE id = ?", (other, item))
            return result

        with patch.object(inbox, "_create_box_copy", racing), self.assertRaises(inbox.BoxCopyIncomplete) as caught:
            self.copy(item)
        self.assertEqual(caught.exception.stage, "register")
        self.assertEqual(self.item_state(item)["copied_to_box_path"], other)

    def test_success_metadata_is_written_only_after_verification(self):
        item = self.add_item()
        seen = []
        real_create, real_register = inbox._create_box_copy, inbox._register_box_copy

        def checked_create(*args, **kwargs):
            state = self.item_state(item)
            seen.append(("create", state["status"], state["copied_to_box_path"], state["linked_document_path"],
                         len(self.events(item, "copied_to_box"))))
            return real_create(*args, **kwargs)

        def checked_register(item_id, expedient_id, client_id, dest, previous, trace):
            state = self.item_state(item)
            seen.append(("register", state["status"], sha(Path(dest).read_bytes()) == trace["source_sha256"],
                         trace["destination_sha256"] == trace["source_sha256"], "verified_at" in trace))
            return real_register(item_id, expedient_id, client_id, dest, previous, trace)

        with patch.object(inbox, "_create_box_copy", checked_create), \
                patch.object(inbox, "_register_box_copy", checked_register):
            self.copy(item)
        self.assertEqual(seen, [("create", "linked", None, None, 0), ("register", "linked", True, True, True)])

    def test_already_copied_item_is_not_copied_again(self):
        item = self.add_item()
        first = self.copy(item)
        events = self.events(item)
        second = self.copy(item, subfolder="02 LABORAL")
        self.assertEqual(second["box_copy"]["result"], "already_copied")
        self.assertEqual(second["copied_to_box_path"], first["copied_to_box_path"])
        self.assertEqual(self.events(item), events)
        self.assertEqual(list((self.box / "02 LABORAL").glob("*.pdf")), [])

    def test_registered_copy_that_differs_requires_review(self):
        item = self.add_item()
        result = self.copy(item)
        self.seed(Path(result["copied_to_box_path"]), b"editado en Box")
        self.protect_box()
        self.assert_refused(item)

    def test_registered_copy_that_disappeared_can_be_copied_again(self):
        item = self.add_item()
        first = Path(self.copy(item)["copied_to_box_path"])
        self.real["unlink"](first)       # simulates a manual removal in Box, outside the service
        result = self.copy(item, subfolder="01 IDENTIDAD")
        self.assert_registered(item, result, self.box / "01 IDENTIDAD" / "Pasaporte.pdf")
        self.assertEqual(len(self.events(item, "copied_to_box")), 2)


class CompatibilityTests(BoxCopyBase):
    def test_signature_and_return_stay_compatible(self):
        params = inspect.signature(inbox.copy_inbox_item_to_expedient_box).parameters
        self.assertEqual(list(params)[:4], ["item_id", "expedient_id", "subfolder", "target_filename"])
        self.assertEqual([params[name].default for name in list(params)[1:4]], [None, "", ""])
        self.assertEqual(params["nomenclature_key"].kind, inspect.Parameter.KEYWORD_ONLY)
        item = self.add_item()
        result = inbox.copy_inbox_item_to_expedient_box(item, 42, "01 IDENTIDAD", "Canonico")
        for key in ("id", "status", "client_id", "expedient_id", "copied_to_box_path", "copied_to_box_at",
                    "linked_document_path", "original_filename", "stored_path"):
            self.assertIn(key, result)
        self.assertTrue(issubclass(inbox.BoxCopyRejected, ValueError))

    def test_item_expedient_is_used_when_none_is_given(self):
        item = self.add_item()
        result = inbox.copy_inbox_item_to_expedient_box(item)
        self.assert_registered(item, result, self.box / "Pasaporte.pdf")
        self.assert_refused(self.add_item(expedient_id=None, status="pending"), error=ValueError,
                            expedient_id=None)

    def test_existing_callers_use_only_supported_arguments(self):
        tree = ast.parse(INBOX_VIEW.read_text(encoding="utf-8"))
        for name, function in (("copy_inbox_item_to_expedient_box", inbox.copy_inbox_item_to_expedient_box),
                               ("copy_document_inbox_batch_to_expedient_box",
                                inbox.copy_document_inbox_batch_to_expedient_box)):
            params = inspect.signature(function).parameters
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == name]
            self.assertTrue(calls, name)
            for call in calls:
                self.assertLessEqual(len(call.args), 1)
                self.assertLessEqual({keyword.arg for keyword in call.keywords}, set(params))

    def test_batch_copy_goes_through_the_governed_copy(self):
        ids = [self.add_item(name="Contrato.pdf"), self.add_item(name="Nomina.pdf")]
        batch = inbox.create_document_inbox_batch("Lote", ids, client_id=7, expedient_id=42,
                                                  target_box_folder="02 LABORAL")
        result = inbox.copy_document_inbox_batch_to_expedient_box(batch["id"])
        self.assertEqual(result["copy_result"]["copied_count"], 2)
        self.assertEqual(result["copy_result"]["error_count"], 0)
        for item_id, name in zip(ids, ("Contrato.pdf", "Nomina.pdf")):
            dest = self.box / "02 LABORAL" / name
            state = self.item_state(item_id)
            self.assertEqual((state["status"], state["copied_to_box_path"]), ("copied_to_box", str(dest)))
            self.assertEqual(dest.read_bytes(), self.sources[item_id][1])
            self.assertEqual(len(self.events(item_id, "copied_to_box")), 1)

    def test_batch_with_hostile_folder_is_refused_before_copying(self):
        ids = [self.add_item()]
        batch = inbox.create_document_inbox_batch("Lote", ids, client_id=7, expedient_id=42,
                                                  target_box_folder="../fuera")
        before = self.query("SELECT * FROM document_inbox_batches WHERE id = ?", (batch["id"],))
        tree = self.tree()
        with self.assertRaises(inbox.BoxCopyRejected):
            inbox.copy_document_inbox_batch_to_expedient_box(batch["id"])
        self.assertEqual(self.query("SELECT * FROM document_inbox_batches WHERE id = ?", (batch["id"],)), before)
        self.assertEqual(self.tree(), tree)
        self.assertEqual(self.item_state(ids[0])["status"], "linked")


if __name__ == "__main__":
    unittest.main()
