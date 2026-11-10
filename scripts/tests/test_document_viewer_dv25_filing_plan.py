"""WO-DV25-P3A: destination folder and nomenclature preview in the link dialog (no copy).

Reuses the DV24 linking fixtures: synthetic PDFs and a synthetic SQLite CRM in a
TemporaryDirectory, ``connection.DB_PATH`` redirected to it, the canonical
``link_inbox_item`` running for real and every other Bandeja/Box mutation
patched to fail. On top of that this suite adds a synthetic classification
catalog and a synthetic Box tree, and patches the catalog's ``ensure_schema``
to fail: P3A must never migrate. ``guard()`` makes any filesystem write
outside the viewer's preview cache fail the test.
"""
import ast
import os
import shutil
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.repositories import document_viewer_notes_repository as notes_repository
from backend.services import document_classification_catalog_service as catalog_service
from backend.services import document_viewer_filing_plan_service as filing
from backend.services import document_viewer_link_service as link_service
from backend.services import document_viewer_notes_service as notes_service
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_label, viewer_layout,
)
from scripts.tests import test_document_viewer_dv24_linking as dv24


FILING = dv24.REPO_ROOT / "backend" / "services" / "document_viewer_filing_plan_service.py"

CATALOG_SQL = """
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
ALTER TABLE expedientes ADD COLUMN tipo_expediente_id INTEGER;
ALTER TABLE expedientes ADD COLUMN subtipo_expediente_id INTEGER;
ALTER TABLE expedientes ADD COLUMN box_folder_path TEXT;
INSERT INTO config_tipos_expediente VALUES (1, 'ARRAIGO', 'Arraigo'), (2, 'NACIONALIDAD', 'Nacionalidad');
INSERT INTO config_subtipos_expediente VALUES (10, 1, 'SOCIAL', 'Social'), (11, 1, 'LABORAL', 'Laboral');
INSERT INTO config_documentos_catalogo (id, codigo, nombre, categoria, activo) VALUES
    (100, 'PASAPORTE', 'PASAPORTE', 'IDENTIDAD', 1),
    (101, 'CONTRATO', 'CONTRATO DE TRABAJO', 'LABORAL', 1),
    (102, 'VIDA_LABORAL', 'VIDA LABORAL', 'LABORAL', 1),
    (103, 'CERT_NACIMIENTO', 'CERTIFICADO DE NACIMIENTO', 'REGISTRO', 1),
    (104, 'RETIRADO', 'DOCUMENTO RETIRADO', 'OTROS', 0),
    (200, 'ADMISION_TRAMITE', 'ADMISIÓN A TRÁMITE', 'TRAMITACION', 1),
    (201, 'RESOLUCION_CONCESION', 'RESOLUCIÓN DE CONCESIÓN', 'RESOLUCION', 1);
-- family (tipo) wide, subtype only, a repeated pattern, another role, another family, inactive.
INSERT INTO config_nomenclaturas_catalogo
    (tipo_expediente_id, subtipo_expediente_id, documento_catalogo_id, rol_documental, prioridad) VALUES
    (1, NULL, 100, 'SOLICITANTE', 10), (1, NULL, 100, 'SOLICITANTE', 20), (1, 10, 101, NULL, 30),
    (1, 11, 102, NULL, 5), (1, NULL, 100, 'FAMILIAR', 40), (2, NULL, 103, NULL, 10),
    (1, NULL, 104, NULL, 1);
INSERT INTO config_nomenclaturas_procedimentales (documento_catalogo_id, patron_nombre, prioridad)
VALUES (200, 'ADMISION A TRAMITE', 10), (201, 'RESOLUCION DE CONCESION', 20);
UPDATE expedientes SET tipo_expediente_id = 1, subtipo_expediente_id = 10 WHERE id = 42;
UPDATE expedientes SET tipo_expediente_id = 1, subtipo_expediente_id = 11 WHERE id = 43;
UPDATE expedientes SET tipo_expediente_id = 2 WHERE id = 50;
"""
PROCEDURAL = ["ADMISIÓN A TRÁMITE", "RESOLUCIÓN DE CONCESIÓN"]
LABELS_42 = ["PASAPORTE · SOLICITANTE", "CONTRATO DE TRABAJO", "PASAPORTE · FAMILIAR", *PROCEDURAL]
KEYS_42 = ["EXPEDIENTE:100:SOLICITANTE", "EXPEDIENTE:101:", "EXPEDIENTE:100:FAMILIAR",
           "PROCEDIMIENTO:200:", "PROCEDIMIENTO:201:"]
LABELS_43 = ["VIDA LABORAL", "PASAPORTE · SOLICITANTE", "PASAPORTE · FAMILIAR", *PROCEDURAL]
FOLDERS_42 = [filing.ROOT_LABEL, "01 IDENTIDAD", "02 LABORAL", "02 LABORAL/Contratos"]
EXISTING = "01 IDENTIDAD/PASAPORTE SOLICITANTE.pdf"
# Calls that would mean a copy, a write to Box/CRM or a migration.
FORBIDDEN_CALLS = {
    "copy_inbox_item_to_expedient_box", "copy_document_inbox_batch_to_expedient_box",
    "link_inbox_item", "update_inbox_item_status", "update_inbox_item_filename",
    "import_file_to_inbox", "create_document_inbox_batch", "mkdir", "makedirs", "rename",
    "unlink", "rmdir", "touch", "write_text", "write_bytes", "copy2", "copyfile", "copytree",
    "rmtree", "ensure_schema", "list_options_for_expedient", "executescript", "commit",
    "get_connection", "get_existing_connection", "symlink",
}


def called_names(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None))
    return names - {None}


def attributes_of(path, owner):
    return {node.attr for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == owner}


class FilingBase(dv24.ViewerBase):
    def setUp(self):
        super().setUp()
        self.archive = self.root / "archivo"
        self.box = self.archive / "EXP-42"
        self.box43 = self.archive / "EXP-43"
        for folder in ("01 IDENTIDAD", "02 LABORAL/Contratos", ".oculta", "~temporal"):
            (self.box / folder).mkdir(parents=True)
        (self.box43 / "Requerimientos").mkdir(parents=True)
        (self.box / EXISTING).write_bytes(b"%PDF existente")
        (self.box / "suelto.txt").write_text("x", encoding="utf-8")
        (self.root / "fuera" / "secreta").mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(CATALOG_SQL)
            conn.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = 42", (str(self.box),))
            conn.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = 43", (str(self.box43),))
            conn.commit()
        # The viewer runs on a CRM with the DV24-P2 notes table; apply that migration to the
        # temporary DB before the snapshot so tearDown only measures what P3A and navigation do.
        notes_repository.ensure_schema(db_path=self.db)
        # P3A never migrates: the catalog's schema helper must not run.
        self.real_ensure_schema = catalog_service.ensure_schema
        self.ensure_schema = self.patch(catalog_service, "ensure_schema",
                                        side_effect=AssertionError("ensure_schema"))
        self.physical = []
        self.archive_before = self.tree()
        self.schema_before = self.schema()

    def tearDown(self):
        self.assertEqual(self.tree(), self.archive_before)
        self.assertEqual(self.schema(), self.schema_before)
        self.assertEqual(self.physical, [])
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    def tree(self):
        """(relative path, kind, bytes) of the synthetic Box tree; links are not followed."""
        entries, base = [], self.archive.resolve()
        pending = [base]
        while pending:
            folder = pending.pop()
            for child in sorted(folder.iterdir()):
                relative = child.relative_to(base).as_posix()
                if child.is_symlink() or child.resolve() != child:
                    entries.append((relative, "link", None))
                elif child.is_dir():
                    entries.append((relative, "dir", None))
                    pending.append(child)
                else:
                    entries.append((relative, "file", child.read_bytes()))
        return sorted(entries, key=lambda entry: entry[0])

    def schema(self):
        return self.query("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")

    @contextmanager
    def guard(self):
        """Any filesystem write outside the viewer's preview cache is recorded and fails."""
        previews = (self.root / "previews").resolve()

        def guarded(name, original):
            def wrapper(*args, **kwargs):
                target = Path(os.fspath(args[0])).resolve() if args else None
                if target is None or (target != previews and previews not in target.parents):
                    self.physical.append((name, str(target)))
                    raise AssertionError(f"{name}: {target}")
                return original(*args, **kwargs)
            return wrapper

        targets = [(os, name) for name in ("mkdir", "makedirs", "rename", "replace", "remove",
                                           "unlink", "rmdir", "symlink")]
        targets += [(shutil, name) for name in ("copy", "copy2", "copyfile", "copytree", "move",
                                                "rmtree")]
        targets += [(Path, name) for name in ("touch", "write_bytes", "write_text")]
        patchers = [patch.object(owner, name, guarded(name, getattr(owner, name)))
                    for owner, name in targets]
        for patcher in patchers:
            patcher.start()
        try:
            yield
        finally:
            for patcher in reversed(patchers):
                patcher.stop()

    def context(self, client_id=7, expedient_id=42):
        return filing.load_context(client_id, expedient_id, db_path=self.db)

    def checks(self, *documents):
        return link_service.inspect_documents(self.actor, documents, db_path=self.db)

    def set_box(self, expedient_id, value):
        self.execute("UPDATE expedientes SET box_folder_path = ? WHERE id = ?", (value, expedient_id))

    @staticmethod
    def labels_of(select):
        return [option["label"] for option in select.options]

    @staticmethod
    def choose(select, label):
        select.select(next(option for option in select.options if option["label"] == label))

    @staticmethod
    def by_key(form):
        return {row.key: row for row in form.preview}

    def open_form(self, dialog, command="Vincular a expediente"):
        self.button(dialog, command).on_click(None)
        return self.form()


class CatalogTests(FilingBase):
    def test_specific_options_by_family_and_subtype_then_procedural(self):
        cases = {
            42: LABELS_42,                                        # family + subtype SOCIAL
            43: LABELS_43,                                        # family + subtype LABORAL
            50: ["CERTIFICADO DE NACIMIENTO", *PROCEDURAL],      # another family
            52: PROCEDURAL,                                       # no type: transversal only
        }
        for expedient_id, labels in cases.items():
            with self.subTest(expedient=expedient_id):
                options, notices = filing.catalog_options(expedient_id, db_path=self.db)
                self.assertEqual([option.label for option in options], labels)
                self.assertEqual(notices, ())
                self.assertTrue(all(option.expedient_id == expedient_id for option in options))
        options, _ = filing.catalog_options(42, db_path=self.db)
        self.assertEqual([option.key for option in options], KEYS_42)
        self.assertEqual([(o.documento_catalogo_id, o.codigo, o.rol_documental, o.origen) for o in options], [
            (100, "PASAPORTE", "SOLICITANTE", filing.SPECIFIC), (101, "CONTRATO", None, filing.SPECIFIC),
            (100, "PASAPORTE", "FAMILIAR", filing.SPECIFIC),
            (200, "ADMISION_TRAMITE", None, filing.PROCEDURAL),
            (201, "RESOLUCION_CONCESION", None, filing.PROCEDURAL)])
        self.assertEqual(options[0].stem, "PASAPORTE SOLICITANTE")
        self.assertEqual(options[0].subtitle, "Específica del expediente · PASAPORTE")
        self.assertEqual(options[3].subtitle, "Transversal · ADMISION_TRAMITE")
        self.ensure_schema.assert_not_called()

    def test_same_contract_as_list_options_for_expedient(self):
        # The canonical function migrates, so it only runs on a throwaway copy.
        copy = self.root / "catalogo_copia.db"
        shutil.copyfile(self.db, copy)
        with patch.object(catalog_service, "ensure_schema", self.real_ensure_schema):
            canonical = catalog_service.list_options_for_expedient(42, db_path=copy)
        ours, _ = filing.catalog_options(42, db_path=copy)
        self.assertEqual(
            [(o.documento_catalogo_id, o.codigo, o.rol_documental, o.origen, o.nombre) for o in ours],
            [(o["documento_catalogo_id"], o["codigo"], o["rol_documental"], o["origen"], o["nombre"])
             for o in canonical["options"]])
        self.assertEqual(len([o for o in ours if o.origen == filing.SPECIFIC]), len(canonical["specific"]))
        self.assertEqual([o.label for o in ours][:3], LABELS_42[:3])

    def test_reading_the_catalog_never_migrates_or_creates(self):
        self.execute("DROP TABLE config_nomenclaturas_procedimentales")
        self.schema_before = self.schema()
        options, notices = filing.catalog_options(42, db_path=self.db)
        self.assertEqual([option.label for option in options], LABELS_42[:3])
        self.assertEqual(notices, (filing.SCHEMA_PENDING.format(kind="transversales"),))
        self.assertNotIn("config_nomenclaturas_procedimentales", [row["name"] for row in self.schema()])
        # A missing database is reported, never created.
        missing = self.root / "no_existe.db"
        self.assertEqual(filing.catalog_options(42, db_path=missing), ((), (filing.CATALOG_UNAVAILABLE,)))
        self.assertFalse(missing.exists())
        # Unknown expediente or a CRM without the catalog: unavailable, no exception.
        self.assertEqual(filing.catalog_options(999, db_path=self.db), ((), (filing.CATALOG_UNAVAILABLE,)))
        self.ensure_schema.assert_not_called()

    def test_labels_stay_unambiguous(self):
        raw = [{"label": "A", "codigo": "X", "origen": "EXPEDIENTE", "documento_catalogo_id": 1},
               {"label": "A", "codigo": "Y", "origen": "EXPEDIENTE", "documento_catalogo_id": 2},
               {"label": "A", "codigo": "Y", "origen": "PROCEDIMIENTO", "documento_catalogo_id": 2},
               {"label": "A", "codigo": "Y", "origen": "PROCEDIMIENTO", "documento_catalogo_id": 3}]
        self.assertEqual(filing._unique_labels(raw),
                         ["A", "A (Y)", "A (Y) · PROCEDIMIENTO", "A · #3"])


class RootAndFolderTests(FilingBase):
    def test_wrong_client_or_expediente_is_refused(self):
        for client_id, expedient_id, message in ((8, 42, "no pertenece al cliente"), (7, 50, "no pertenece"),
                                                 (7, 999, "no existe"), (7, 51, "archivado"),
                                                 (7, 52, "no tiene cliente"), (None, 42, "Selecciona")):
            with self.subTest(client=client_id, expedient=expedient_id), \
                    self.assertRaises(filing.FilingPlanError) as raised:
                self.context(client_id, expedient_id)
            self.assertIn(message, str(raised.exception))

    def test_folders_are_existing_relative_and_never_created(self):
        context = self.context()
        self.assertTrue(context.root.available)
        self.assertEqual(context.root.path, self.box.resolve())
        self.assertEqual([folder.label for folder in context.folders], FOLDERS_42)
        self.assertEqual([folder.relative for folder in context.folders],
                         ["", "01 IDENTIDAD", "02 LABORAL", "02 LABORAL/Contratos"])
        self.assertEqual(context.notices, ())
        # Empty root: only the root itself, with a notice.
        self.set_box(43, str(self.box43 / "Requerimientos"))
        context = self.context(7, 43)
        self.assertEqual([folder.relative for folder in context.folders], [""])
        self.assertEqual(context.notices, (filing.NO_FOLDERS,))

    def test_root_missing_or_without_access_blocks_only_the_destination(self):
        cases = {"no box": None, "missing": str(self.root / "no-existe"),
                 "file": str(self.box / "suelto.txt"), "relative": "archivo/EXP-42"}
        for name, value in cases.items():
            with self.subTest(name):
                self.set_box(42, value)
                context = self.context()
                self.assertEqual((context.root.available, context.folders), (False, ()))
                self.assertEqual(context.notices[0], filing.NO_BOX)
                self.assertEqual([o.label for o in context.options], LABELS_42)
        self.assertFalse((self.root / "no-existe").exists())
        self.set_box(42, str(self.box))
        with patch.object(Path, "is_dir", side_effect=PermissionError("denegado")):
            self.assertFalse(filing.expedient_root(42).available)
        with patch.object(filing, "list_expediente_box_directory", side_effect=PermissionError("denegado")):
            context = self.context()
            self.assertEqual([folder.relative for folder in context.folders], [""])
            rows = filing.build_preview(context, self.checks(self.doc(1)), folder="",
                                        choices={"inbox:1": KEYS_42[0]})
            self.assertEqual((rows[0].status, rows[0].message),
                             (filing.BLOCKED, "Sin acceso a la carpeta destino."))

    def test_traversal_absolute_and_unknown_folders_are_refused(self):
        context = self.context()
        self.assertEqual(filing.verify_folder(context, ""), "")
        self.assertEqual(filing.verify_folder(context, "02 LABORAL\\Contratos"), "02 LABORAL/Contratos")
        for value in ("..", "../fuera", "..\\fuera", "01 IDENTIDAD/../..", "./01 IDENTIDAD",
                      "01 IDENTIDAD/", "/01 IDENTIDAD", str(self.box / "01 IDENTIDAD"),
                      str(self.root / "fuera"), "C:/Windows", "C:fuera", "\\\\servidor\\x",
                      ".oculta", "~temporal", "no-existe", "01 IDENTIDAD/" + EXISTING.split("/")[1],
                      "01 IDENTIDAD\x00", None, 42, b"01 IDENTIDAD"):
            with self.subTest(value=value):
                self.assertIsNone(filing.verify_folder(context, value))
        # A listed folder that disappears afterwards is no longer valid.
        (self.box / "02 LABORAL" / "Contratos").rmdir()
        self.archive_before = self.tree()
        self.assertIsNone(filing.verify_folder(context, "02 LABORAL/Contratos"))

    def test_links_leaving_the_root_are_never_offered(self):
        outside = self.root / "fuera"
        made = []
        try:
            os.symlink(outside, self.box / "enlace", target_is_directory=True)
            made.append("enlace")
        except (OSError, NotImplementedError):
            pass
        if os.name == "nt":
            import _winapi
            try:
                _winapi.CreateJunction(str(outside), str(self.box / "union"))
                made.append("union")
            except OSError:
                pass
        if not made:
            self.skipTest("No se pueden crear enlaces simbólicos ni uniones en este equipo")
        self.archive_before = self.tree()
        context = self.context()
        self.assertEqual([folder.label for folder in context.folders], FOLDERS_42)
        for name in made:
            with self.subTest(link=name):
                self.assertIsNone(filing.verify_folder(context, name))
                self.assertIsNone(filing.verify_folder(context, f"{name}/secreta"))
        # A root that is itself a link is not accepted either.
        if "enlace" in made:
            self.set_box(42, str(self.box / "enlace"))
            self.assertFalse(filing.expedient_root(42).available)


class PreviewTests(FilingBase):
    def test_names_keep_the_real_extension_and_avoid_reserved_characters(self):
        cases = {
            'A<B>:C"D/E\\F|G?H*I': "A_B__C_D_E_F_G_H_I",
            "CON": "CON_", "nul": "nul_", "LPT1": "LPT1_", "COM1.informe": "COM1.informe_",
            "  .Informe   final. ": "Informe final", "a\x01b\tc": "a_b_c", "...": "",
            "Z" * 300: "Z" * filing.MAX_STEM,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(filing.safe_stem(value), expected)
        context = self.context()
        check = self.checks(self.doc(1))[0]
        base = replace(context.options[0], key="x", nombre='CON', rol_documental=None)
        custom = replace(context, options=(base, replace(base, key="vacio", nombre="..."),
                                           replace(base, key="reservado", nombre='INFORME "A/B"')))
        documents = [replace(check, key="pdf"), replace(check, key="mayus", path=str(self.root / "x.PDF")),
                     replace(check, key="sin", path=str(self.root / "sin_extension")),
                     replace(check, key="raro", path=str(self.root / "x.p d f")),
                     replace(check, key="vacio"), replace(check, key="reservado")]
        rows = filing.build_preview(custom, documents, folder="02 LABORAL", choices={
            "pdf": "x", "mayus": "x", "sin": "x", "raro": "x", "vacio": "vacio", "reservado": "reservado"})
        self.assertEqual([(row.proposed_name, row.status) for row in rows], [
            ("CON_.pdf", filing.PROPOSED), ("CON__2.PDF", filing.COLLISION), ("", filing.BLOCKED),
            ("", filing.BLOCKED), ("", filing.BLOCKED), ("INFORME _A_B.pdf", filing.PROPOSED)])
        self.assertEqual(rows[2].message, "El origen no tiene una extensión válida.")
        self.assertEqual(rows[4].message, "La nomenclatura no produce un nombre de archivo válido.")

    def test_collisions_are_only_projected(self):
        context = self.context()
        checks = self.checks(self.doc(1), self.doc(2), self.doc(3))
        choice = {"inbox:1": KEYS_42[0], "inbox:2": KEYS_42[0], "inbox:3": KEYS_42[3]}
        rows = filing.build_preview(context, checks, folder="01 IDENTIDAD", choices=choice)
        self.assertEqual([(row.proposed_name, row.status, row.folder) for row in rows], [
            ("PASAPORTE SOLICITANTE_2.pdf", filing.COLLISION, "01 IDENTIDAD"),
            ("PASAPORTE SOLICITANTE_3.pdf", filing.COLLISION, "01 IDENTIDAD"),
            ("ADMISIÓN A TRÁMITE.pdf", filing.PROPOSED, "01 IDENTIDAD")])
        # Projected names are not reserved: the same preview again gives the same names.
        self.assertEqual(filing.build_preview(context, checks, folder="01 IDENTIDAD", choices=choice), rows)
        rows = filing.build_preview(context, checks, folder="", choices=choice)
        self.assertEqual([row.proposed_name for row in rows], [
            "PASAPORTE SOLICITANTE.pdf", "PASAPORTE SOLICITANTE_2.pdf", "ADMISIÓN A TRÁMITE.pdf"])
        self.assertEqual(rows[0].folder, filing.ROOT_LABEL)
        self.assertFalse((self.box / "01 IDENTIDAD" / "PASAPORTE SOLICITANTE_2.pdf").exists())
        self.assertFalse((self.box / "PASAPORTE SOLICITANTE.pdf").exists())

    def test_zero_one_many_and_every_state(self):
        context = self.context()
        self.assertEqual(filing.build_preview(context, (), folder="", choices={}), ())
        one = filing.build_preview(context, self.checks(self.doc(1)), folder="",
                                   choices={"inbox:1": KEYS_42[1]})
        self.assertEqual([(r.inbox_item_id, r.nomenclature, r.proposed_name) for r in one],
                         [(1, "CONTRATO DE TRABAJO", "CONTRATO DE TRABAJO.pdf")])
        checks = self.checks(self.doc(1), self.doc(2), self.doc(5), self.doc(8), self.doc(7),
                             self.doc(99), self.box_doc(), self.doc(4), self.doc(6))
        rows = filing.build_preview(context, checks, folder=None, choices={"inbox:2": KEYS_42[0]})
        self.assertEqual([row.status for row in rows], [
            filing.PENDING, filing.PENDING, filing.BLOCKED, filing.BLOCKED, filing.BLOCKED,
            filing.BLOCKED, filing.NO_INBOX, filing.PENDING, filing.PENDING])
        self.assertIn("nomenclatura", rows[0].message)
        self.assertIn("carpeta", rows[1].message)
        self.assertIn("Descartado", rows[2].message)
        self.assertIn("duplicado", rows[3].message)
        self.assertIn("Ya copiado a Box", rows[4].message)
        self.assertEqual(rows[5].message, link_service.ITEM_MISSING)
        self.assertEqual((rows[6].inbox_item_id, rows[6].proposed_name), (None, ""))
        # The transfer (4) and the already linked (6) can still get a proposal.
        self.assertEqual([filing.blocker(context, check) for check in checks[7:]], ["", ""])

    def test_options_of_another_expediente_are_never_applied(self):
        context43 = self.context(7, 43)
        check = self.checks(self.doc(1))
        # CONTRATO only belongs to expediente 42's catalog; a free text is not a key either.
        for choice in (KEYS_42[1], "PASAPORTE", "PASAPORTE · SOLICITANTE", None):
            with self.subTest(choice=choice):
                rows = filing.build_preview(context43, check, folder="", choices={"inbox:1": choice})
                self.assertEqual(rows[0].status, filing.PENDING)
        foreign = replace(self.context().options[0], expedient_id=42)
        tampered = replace(context43, options=(foreign,))
        rows = filing.build_preview(tampered, check, folder="", choices={"inbox:1": foreign.key})
        self.assertEqual(rows[0].status, filing.PENDING)


class DialogTests(FilingBase):
    def test_single_preview_with_only_the_logical_link_executable(self):
        dialog = self.open_inbox([1, 2])
        before = self.row(1)
        with self.guard():
            form = self.open_form(dialog)
            texts = self.texts(form.dialog)
            self.assertIn(filing.PREVIEW_ONLY, texts)
            self.assertIn(f"Vincular y archivar copia: {filing.ARCHIVE_PENDING}.", texts)
            archive = form.archive_button
            self.assertIn(archive, form.dialog.actions)
            self.assertEqual(viewer_action_label(archive), "Vincular y archivar copia")
            self.assertTrue(archive.disabled)
            self.assertIsNone(archive.on_click)
            self.assertEqual(archive.tooltip, filing.ARCHIVE_PENDING)
            self.assertIsNone(form.filing)  # client preselected, expediente not chosen yet

            self.pick(form.expedient_select, 42)
            self.assertEqual(form.filing.target.expedient_id, 42)
            self.assertEqual(self.labels_of(form.folder_select), FOLDERS_42)
            self.assertEqual(list(form.nomenclature_selects), ["inbox:1"])
            select = form.nomenclature_selects["inbox:1"]
            self.assertEqual(self.labels_of(select), LABELS_42)
            self.assertEqual(form.preview[0].status, filing.PENDING)
            self.choose(select, "PASAPORTE · SOLICITANTE")
            self.assertEqual(form.preview[0].status, filing.PENDING)  # folder still missing
            self.choose(form.folder_select, "01 IDENTIDAD")
            row = form.preview[0]
            self.assertEqual((row.source_name, row.inbox_item_id, row.nomenclature, row.folder,
                              row.proposed_name, row.status),
                             ("Pasaporte 1.pdf", 1, "PASAPORTE · SOLICITANTE", "01 IDENTIDAD",
                              "PASAPORTE SOLICITANTE_2.pdf", filing.COLLISION))
            self.choose(form.folder_select, filing.ROOT_LABEL)
            self.assertEqual((form.preview[0].proposed_name, form.preview[0].status),
                             ("PASAPORTE SOLICITANTE.pdf", filing.PROPOSED))
            # Choosing destination and nomenclature does not touch the link confirmation.
            self.assertTrue(form.submit_button.disabled)

            self.confirm(form)
            form.submit_button.on_click(None)
            self.link.assert_called_once_with(1, client_id=7, expedient_id=42)
            after = self.row(1)
            self.assertEqual((after["expedient_id"], after["status"]), (42, "linked"))
            for column in ("stored_path", "stored_filename", "original_filename", "linked_document_path",
                           "copied_to_box_path", "copied_to_box_at", "metadata_json", "notes"):
                self.assertEqual(after[column], before[column], column)
            self.assertEqual([e["event_type"] for e in self.events(1)], ["linked"])
            self.assertNotIn("PASAPORTE SOLICITANTE", str(self.query("SELECT * FROM document_inbox_events")))
            self.assertTrue(archive.disabled)
            form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_changing_client_or_expediente_invalidates_every_choice(self):
        dialog = self.open_inbox([1, 2])
        with self.guard():
            form = self.open_form(dialog)
            self.pick(form.expedient_select, 42)
            self.choose(form.folder_select, "01 IDENTIDAD")
            self.choose(form.nomenclature_selects["inbox:1"], "CONTRATO DE TRABAJO")
            self.confirm(form)
            self.assertFalse(form.submit_button.disabled)
            old_context, old_folder = form.filing, form.folder_select
            old_select = form.nomenclature_selects["inbox:1"]

            self.pick(form.expedient_select, 43)
            self.assertIsNot(form.filing, old_context)
            self.assertEqual(form.filing.target.expedient_id, 43)
            self.assertEqual((form.folder, form.choices), (None, {}))
            self.assertFalse(form.confirm.value)
            self.assertTrue(form.submit_button.disabled)
            self.assertEqual(self.labels_of(form.folder_select), [filing.ROOT_LABEL, "Requerimientos"])
            self.assertEqual(self.labels_of(form.nomenclature_selects["inbox:1"]), LABELS_43)
            self.assertEqual(form.preview[0].status, filing.PENDING)
            # Late events of the previous expediente's selectors are ignored.
            self.choose(old_select, "CONTRATO DE TRABAJO")
            self.choose(old_folder, "02 LABORAL")
            self.assertEqual((form.folder, form.choices), (None, {}))
            # A label that is not an option of this expediente is not accepted (no free text).
            form._on_nomenclature(form.filing, "inbox:1", "CONTRATO DE TRABAJO")
            form._on_folder(form.filing, "../fuera")
            self.assertEqual((form.folder, form.choices), (None, {}))

            self.choose(form.folder_select, "Requerimientos")
            self.choose(form.nomenclature_selects["inbox:1"], "VIDA LABORAL")
            self.assertEqual(form.preview[0].proposed_name, "VIDA LABORAL.pdf")
            self.pick(form.client_select, 8)
            self.assertEqual((form.filing, form.folder, form.choices, form.preview), (None, None, {}, ()))
            self.assertEqual((form.folder_select, form.nomenclature_selects), (None, {}))
            self.assertTrue(form.submit_button.disabled)
            form.cancel_button.on_click(None)
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_batch_gets_options_per_document_and_never_in_bulk(self):
        dialog = self.open_inbox([1, 2, 5, 3])
        self.button(dialog, "Comparador 4").on_click(None)
        for tile in (0, 1, 2):
            self.check(dialog, tile, True)
        # Unchecking before opening removes the document from the form and its preview.
        self.check(dialog, 2, False)
        self.check(dialog, 2, True)
        with self.guard():
            form = self.open_form(dialog, "Vincular seleccionados")
            self.assertEqual([request["inbox_item_id"] for request in form.requests], [1, 2, 5])
            self.pick(form.expedient_select, 42)
            self.assertEqual(list(form.nomenclature_selects), ["inbox:1", "inbox:2"])
            rows = self.by_key(form)
            self.assertEqual(rows["inbox:5"].status, filing.BLOCKED)
            self.assertIn("Descartado", rows["inbox:5"].message)
            self.choose(form.folder_select, "01 IDENTIDAD")
            self.choose(form.nomenclature_selects["inbox:1"], "PASAPORTE · SOLICITANTE")
            rows = self.by_key(form)
            self.assertEqual(rows["inbox:1"].proposed_name, "PASAPORTE SOLICITANTE_2.pdf")
            self.assertEqual((rows["inbox:2"].status, rows["inbox:2"].proposed_name), (filing.PENDING, ""))
            self.assertEqual(form.choices, {"inbox:1": KEYS_42[0]})
            self.choose(form.nomenclature_selects["inbox:2"], "PASAPORTE · SOLICITANTE")
            self.assertEqual(self.by_key(form)["inbox:2"].proposed_name, "PASAPORTE SOLICITANTE_3.pdf")
            self.choose(form.nomenclature_selects["inbox:2"], "ADMISIÓN A TRÁMITE")
            rows = self.by_key(form)
            self.assertEqual((rows["inbox:1"].proposed_name, rows["inbox:2"].proposed_name),
                             ("PASAPORTE SOLICITANTE_2.pdf", "ADMISIÓN A TRÁMITE.pdf"))
            # Clearing a choice (unknown label) only changes that document's preview.
            form._on_nomenclature(form.filing, "inbox:2", "texto libre")
            self.assertEqual(form.choices, {"inbox:1": KEYS_42[0]})
            self.assertEqual(self.by_key(form)["inbox:2"].status, filing.PENDING)
            form.cancel_button.on_click(None)
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_documents_without_bandeja_are_not_faked(self):
        exp_doc = self.exp_docs[0]
        queue = [{"path": str(self.inbox_docs[1]), "name": "Pasaporte 1.pdf", "key": "inbox:1",
                  "inbox_item_id": 1},
                 {"path": str(exp_doc), "name": exp_doc.name, "key": "expedient:42:contrato"}]
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], queue=queue, near_window=0,
                                            linking=self.linking())
        self.button(dialog, "Comparador 4").on_click(None)
        self.check(dialog, 0, True)
        self.check(dialog, 1, True)
        with self.guard():
            form = self.open_form(dialog, "Vincular seleccionados")
            self.pick(form.expedient_select, 42)
            self.assertEqual(list(form.nomenclature_selects), ["inbox:1"])
            row = self.by_key(form)["expedient:42:contrato"]
            self.assertEqual((row.inbox_item_id, row.status, row.proposed_name), (None, filing.NO_INBOX, ""))
            form.cancel_button.on_click(None)
            # Only expediente documents: DV24 behaviour, no selectors and archive still disabled.
            self.check(dialog, 0, False)
            form = self.open_form(dialog, "Vincular seleccionados")
            self.assertEqual(form.status.value, link_service.NOT_LINKABLE_MESSAGE)
            self.assertNotIn(form.filing_column, list(dv24.walk(form.dialog)))
            self.assertTrue(form.archive_button.disabled)
            form.close()
        self.link.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)

    def test_without_local_box_the_destination_is_blocked_but_linking_works(self):
        self.set_box(42, str(self.root / "no-existe"))
        dialog = self.open_inbox([1, 2])
        with self.guard():
            form = self.open_form(dialog)
            self.pick(form.expedient_select, 42)
            self.assertIn(filing.NO_BOX, self.texts(form.dialog))
            self.assertEqual((form.folder_select, form.nomenclature_selects), (None, {}))
            self.assertEqual((form.preview[0].status, form.preview[0].message), (filing.BLOCKED, filing.NO_BOX))
            self.confirm(form)
            form.submit_button.on_click(None)
            self.assertEqual(self.statuses(form.result), {1: link_service.LINKED})
            form.close()
        self.assertFalse((self.root / "no-existe").exists())
        self.assertIsNone(self.row(1)["copied_to_box_path"])
        self.button(dialog, "Cerrar").on_click(None)

    def test_cancel_close_and_navigation_have_no_side_effects(self):
        target = {"inbox_item_id": 2, "path": str(self.inbox_docs[2])}
        notes_service.add_document_note(self.actor, target, "nota", request_id=uuid4().hex, db_path=self.db)
        notes, rows, events = self.query("SELECT * FROM document_viewer_notes"), self.rows(), self.events()
        dialog = self.open_inbox([1, 2, 3], index=1, notes=self.notes())
        self.button(dialog, "Zoom +").on_click(None)
        layout = viewer_layout(dialog)
        state = (layout.document.index, layout.page_label.value, layout.zoom_label.value)
        with self.guard():
            for how in ("cancel", "close"):
                with self.subTest(how=how):
                    form = self.open_form(dialog)
                    self.pick(form.expedient_select, 42)
                    self.choose(form.folder_select, filing.ROOT_LABEL)
                    self.choose(form.nomenclature_selects["inbox:2"], "PASAPORTE · FAMILIAR")
                    self.confirm(form)
                    preview, folder_select = form.preview, form.folder_select
                    form.cancel_button.on_click(None) if how == "cancel" else form.close()
                    self.assertTrue(form.closed)
                    self.assertIsNone(form.submit())
                    self.choose(folder_select, "02 LABORAL")  # late event after closing
                    self.assertIs(form.preview, preview)
                    layout = viewer_layout(dialog)
                    self.assertEqual((layout.document.index, layout.page_label.value,
                                      layout.zoom_label.value), state)
                    self.assertEqual(self.note_bodies(dialog), ["nota"])
            self.button(dialog, "Doc siguiente").on_click(None)
            self.button(dialog, "Doc anterior").on_click(None)
            self.assertEqual(viewer_layout(dialog).document.index, 1)
            self.assertEqual(self.links(dialog).status_text.value, "Sin expediente")
            # Closing the viewer with the form open closes the form, nothing is written.
            form = self.open_form(dialog)
            self.pick(form.expedient_select, 42)
            self.button(dialog, "Cerrar").on_click(None)
            self.assertTrue(form.closed)
        self.link.assert_not_called()
        self.assertEqual((self.query("SELECT * FROM document_viewer_notes"), self.rows(), self.events()),
                         (notes, rows, events))


class ScopeTests(FilingBase):
    def test_no_copy_write_or_migration_is_reachable(self):
        for path in (FILING, dv24.DIALOG):
            with self.subTest(path.name):
                self.assertEqual(called_names(path) & FORBIDDEN_CALLS, set())
                modules = dv24.imported_modules(path)
                for forbidden in ("shutil", "os", "subprocess", "backend.services.box_watch_service"):
                    self.assertFalse(any(m == forbidden or m.startswith(forbidden + ".") for m in modules),
                                     forbidden)
        # The service reads: the expediente through Bandeja's getter, SQL only SELECT, read-only DB.
        self.assertEqual(attributes_of(FILING, "document_inbox_service"), {"get_expedient"})
        self.assertEqual(attributes_of(FILING, "connection"), {"get_readonly_connection"})
        tree = ast.parse(FILING.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "execute":
                self.assertTrue(node.args[0].value.lstrip().upper().startswith("SELECT"))
        self.assertEqual(attributes_of(FILING, "link_service") - {"DocumentLinkError", "READY", "REJECTED"},
                         {"resolve_target", "decide"})
        # The dialog: preview through the service, execute_link still the only operation.
        dialog_calls = {node.func.attr for node in ast.walk(ast.parse(dv24.DIALOG.read_text(encoding="utf-8")))
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and getattr(node.func.value, "id", None) == "filing_service"}
        self.assertEqual(dialog_calls, {"load_context", "build_preview", "blocker"})
        self.assertIn("link_service.execute_link(", dv24.DIALOG.read_text(encoding="utf-8"))
        for text in (FILING.read_text(encoding="utf-8"), dv24.DIALOG.read_text(encoding="utf-8")):
            self.assertNotIn("copy_inbox_item_to_expedient_box", text)
            self.assertNotIn("copy_document_inbox_batch_to_expedient_box", text)

    def test_guard_detects_physical_operations(self):
        with self.guard():
            with self.assertRaises(AssertionError):
                (self.box / "nueva").mkdir()
            with self.assertRaises(AssertionError):
                shutil.copy2(self.box / EXISTING, self.box / "copia.pdf")
        self.assertEqual([name for name, _ in self.physical], ["mkdir", "copy2"])
        self.physical = []


if __name__ == "__main__":
    unittest.main()
