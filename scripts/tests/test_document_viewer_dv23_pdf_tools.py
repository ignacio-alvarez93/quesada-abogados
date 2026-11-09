"""WO-DV23-P2: the seven viewer PDF tools, end to end, from Bandeja and Expedientes.

Synthetic PDFs in a TemporaryDirectory only. The Bandeja registry is an
in-memory fake behind the real document-tools services; no database, no
network, no expediente folders other than the temporary one.
"""
import ast
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as viewer_service
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools import document_viewer_tools_service as tools
from backend.services.document_tools import pdf_tools_service as pdf
from backend.services.document_tools import safe_file_service
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label,
)
from frontend.components.document_viewer_pdf_tools import (
    PdfToolForm, Q_ERROR, Q_SUCCESS, ViewerPdfTools,
)
from frontend.components import pdf_tools_toolbar_adapter as adapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPEDIENTS = REPO_ROOT / "frontend" / "views" / "expedients_view.py"
INBOX = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"

LABELS = dict(adapter.PDF_ACTIONS)
PARAMS = {
    "rotate": {"pages": "2", "degrees": "90"},
    "move_page": {"page_number": "5", "target_position": "1"},
    "split": {"ranges": "1-2,3-5"},
    "compress": {},
    "extract": {"pages": "3,1"},
    "merge": None,  # chosen through the form: candidate first, then the open document
    "annotate": {"page_number": "2", "text": "Nota DV23 sintética", "position": "bottom"},
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_pdf(path, label, pages=5):
    """Uncompressed flat image per page (so smart compression really reduces) plus a text marker."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 300), False)
    pix.set_rect(pix.irect, (200, 220, 240))
    with fitz.open() as doc:
        for index in range(pages):
            page = doc.new_page(width=200, height=200)
            page.insert_image(page.rect, pixmap=pix)
            page.insert_text((10, 20), f"{label}-P{index + 1}", fontsize=9)
        doc.save(path, deflate=False, garbage=0)
    return path


def page_markers(path):
    with fitz.open(path) as doc:
        return [page.get_text().strip() for page in doc]


class ModernPage:
    """Flet >= 0.80 show_dialog/pop_dialog stack; pop dismisses like the client does."""

    def __init__(self):
        self.overlay = []
        self._dialogs = SimpleNamespace(controls=[])
        self.update = Mock()

    def show_dialog(self, dialog):
        if any(item is dialog for item in self._dialogs.controls):
            raise RuntimeError("Dialog is already opened")
        original = dialog.on_dismiss

        def wrapped(e):
            self._dialogs.controls = [d for d in self._dialogs.controls if d is not dialog]
            dialog.on_dismiss = original
            if original:
                original(e)
        dialog.on_dismiss = wrapped
        dialog.open = True
        self._dialogs.controls.append(dialog)

    def pop_dialog(self):
        dialog = self._dialogs.controls[-1]
        dialog.open = False
        dialog.on_dismiss(None)
        return dialog

    @property
    def stack(self):
        return self._dialogs.controls


class FakeInbox:
    """In-memory Bandeja registry behind the real document-tools services."""

    def __init__(self):
        self.items = {}
        self.registered = []
        self.next_id = 100

    def get(self, item_id):
        item = self.items.get(int(item_id))
        if not item:
            raise ValueError("No existe el documento de bandeja indicado.")
        return dict(item)

    def register(self, file_path, source_type, source_label, notes, client_id, expedient_id, metadata_json):
        item = {"id": self.next_id, "stored_path": str(file_path), "original_filename": Path(file_path).name,
                "source_type": source_type, "source_label": source_label, "notes": notes,
                "client_id": client_id, "expedient_id": expedient_id, "metadata_json": metadata_json}
        self.next_id += 1
        self.registered.append(item)
        return dict(item)


class Dv23ToolsBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.tools_root = self.tmp / "tools"

        # Expediente folder (temporary) and a foreign folder outside it.
        self.exp_root = self.tmp / "expediente_42"
        self.exp_source = make_pdf(self.exp_root / "sub" / "contrato.pdf", "EXP")
        self.exp_other = make_pdf(self.exp_root / "anexo.pdf", "ANX", pages=3)
        (self.exp_root / "nota.txt").write_text("no pdf", encoding="utf-8")
        self.foreign = make_pdf(self.tmp / "ajeno" / "ajeno.pdf", "AJENO", pages=2)

        # Bandeja originals.
        self.inbox = FakeInbox()
        self.inbox_source = make_pdf(self.tmp / "inbox" / "a.pdf", "INB")
        self.inbox_other = make_pdf(self.tmp / "inbox" / "b.pdf", "OTR", pages=3)
        self.inbox_alien = make_pdf(self.tmp / "inbox" / "c.pdf", "ALN", pages=2)
        image = self.tmp / "inbox" / "d.png"
        fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5, 5), False).save(image)
        link = {"client_id": 7, "expedient_id": 42}
        self.inbox.items = {
            1: {"id": 1, "stored_path": str(self.inbox_source), "original_filename": "a.pdf", **link},
            2: {"id": 2, "stored_path": str(self.inbox_other), "original_filename": "b.pdf", **link},
            3: {"id": 3, "stored_path": str(self.inbox_alien), "original_filename": "c.pdf",
                "client_id": 7, "expedient_id": 99},
            4: {"id": 4, "stored_path": str(image), "original_filename": "d.png", **link},
        }

        self.protected = [self.exp_source, self.exp_other, self.foreign, self.inbox_source,
                          self.inbox_other, self.inbox_alien]
        self.hashes = {path: sha256(path) for path in self.protected}
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))

        for target, attribute, value in (
            (safe_file_service, "DOCUMENT_TOOLS_ROOT", self.tools_root),
            (viewer_service, "PREVIEW_DIR", self.tmp / "previews"),
            (viewer_service, "get_expediente_document_root",
             Mock(side_effect=self.expediente_root)),
            (inbox_tools, "get_inbox_item", self.inbox.get),
            (inbox_tools, "import_file_to_inbox", self.inbox.register),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.page = ModernPage()
        self.done = Mock()
        self.error = Mock()

    def expediente_root(self, expediente_id):
        if int(expediente_id) != 42:
            return {"exists": False, "root_path": "", "message": "El expediente no tiene carpeta vinculada."}
        return {"exists": True, "root_path": str(self.exp_root), "expediente_id": 42}

    def tearDown(self):
        # Originals are byte-identical and nothing was written into the expediente folder.
        for path, digest in self.hashes.items():
            self.assertEqual(sha256(path), digest, path)
        self.assertEqual(sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*")),
                         self.exp_listing)

    # ------------------------------------------------------------------ helpers

    def scope(self, context):
        if context == "inbox":
            return tools.inbox_scope(1, self.inbox_source, inbox_items=self.inbox.items.values())
        return tools.expedient_scope(42, self.exp_source)

    def source(self, context):
        return self.inbox_source if context == "inbox" else self.exp_source

    def other(self, context):
        return self.inbox_other if context == "inbox" else self.exp_other

    def merge_params(self, scope):
        return {"order": [scope.merge_candidates[0]["key"], "current"]}

    def check_output(self, operation, context, outcome):
        source = self.source(context)
        outputs = [Path(p) for p in outcome["outputs"]]
        self.assertTrue(outputs)
        for output in outputs:
            self.assertTrue(output.is_file())
            self.assertNotEqual(output.resolve(), source.resolve())
            self.assertTrue(output.resolve().is_relative_to(self.tools_root.resolve()), output)
        tag = "INB" if context == "inbox" else "EXP"
        other = "OTR" if context == "inbox" else "ANX"
        markers = page_markers(outputs[0])
        if operation == "rotate":
            with fitz.open(outputs[0]) as doc:
                self.assertEqual([p.rotation for p in doc], [0, 90, 0, 0, 0])
        elif operation == "move_page":
            self.assertEqual(markers, [f"{tag}-P{i}" for i in (5, 1, 2, 3, 4)])
        elif operation == "split":
            self.assertEqual([page_markers(p) for p in outputs],
                             [[f"{tag}-P1", f"{tag}-P2"], [f"{tag}-P{i}" for i in (3, 4, 5)]])
        elif operation == "compress":
            self.assertLess(outputs[0].stat().st_size, source.stat().st_size)
            with fitz.open(outputs[0]) as doc:
                self.assertEqual(doc.page_count, 5)
        elif operation == "extract":
            self.assertEqual(markers, [f"{tag}-P3", f"{tag}-P1"])
        elif operation == "merge":
            self.assertEqual(markers, [f"{other}-P{i}" for i in (1, 2, 3)] + [f"{tag}-P{i}" for i in range(1, 6)])
        elif operation == "annotate":
            with fitz.open(outputs[0]) as doc:
                notes = [(p.number, a.info["content"]) for p in doc for a in p.annots()]
            self.assertEqual(notes, [(1, "Nota DV23 sintética")])
            with fitz.open(source) as doc:
                self.assertEqual([a for p in doc for a in p.annots()], [])
        # Every derivative is registered in Bandeja with traceable provenance.
        registered = outcome["generated_items"]
        self.assertEqual(len(registered), len(outputs))
        for item in registered:
            metadata = item["metadata_json"]
            self.assertEqual(item["source_type"], "generated")
            self.assertEqual(item["expedient_id"], 42)
            if context == "inbox":
                expected_ids = [2, 1] if operation == "merge" else [1]
                self.assertEqual(metadata["source_item_ids"], expected_ids)
            else:
                self.assertEqual(metadata["source_item_ids"], [])
                self.assertEqual(metadata["provenance"]["source_context"], "expedient")
                self.assertEqual(metadata["provenance"]["expediente_id"], 42)
                self.assertEqual(metadata["provenance"]["source_relative_path"], str(Path("sub/contrato.pdf")))
                self.assertEqual(metadata["provenance"]["source_sha256"], self.hashes[self.exp_source])


class ServiceEndToEndTests(Dv23ToolsBase):
    def test_seven_operations_in_both_contexts_create_registered_copies(self):
        for context in ("inbox", "expedient"):
            for operation in tools.OPERATIONS:
                with self.subTest(context=context, operation=operation):
                    scope = self.scope(context)
                    params = PARAMS[operation] or self.merge_params(scope)
                    outcome = tools.run_tool(scope, operation, params, inbox_items=self.inbox.items.values())
                    self.assertTrue(outcome["ok"])
                    self.assertEqual(outcome["scope"], context)
                    self.check_output(operation, context, outcome)

    def test_derivative_names_never_collide_on_repetition(self):
        scope = self.scope("expedient")
        first = tools.run_tool(scope, "extract", {"pages": "1"})
        second = tools.run_tool(scope, "extract", {"pages": "1"})
        self.assertNotEqual(first["outputs"], second["outputs"])

    def test_collision_with_source_is_refused_and_nothing_registered(self):
        for context in ("inbox", "expedient"):
            with self.subTest(context=context):
                scope = self.scope(context)
                with patch.object(pdf, "build_output_path", return_value=self.source(context)):
                    with self.assertRaises(ValueError):
                        tools.run_tool(scope, "rotate", {"pages": "1", "degrees": "90"})
        self.assertEqual(self.inbox.registered, [])

    def test_compression_without_reduction_is_a_visible_error(self):
        tiny = self.exp_root / "tiny.pdf"
        with fitz.open() as doc:
            doc.new_page(width=100, height=100).insert_text((10, 20), "x")
            doc.save(tiny, deflate=True, garbage=4)
        self.hashes[tiny] = sha256(tiny)
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))
        scope = tools.expedient_scope(42, tiny)
        # Deterministic: both candidates come out larger than the original.
        bigger = tiny.stat().st_size + 1
        def fake_basic(source, output_stem=None):
            out = self.tools_root / "compressed" / f"{output_stem}.pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"0" * bigger)
            return pdf.DocumentToolResult.success(operation="pdf_compress_basic",
                                                  source_paths=[source], output_path=out)
        with patch.object(pdf, "compress_pdf_basic", side_effect=fake_basic), \
             patch.object(pdf, "compress_pdf_rasterized",
                          return_value=pdf.DocumentToolResult.failure(operation="r", errors=["sin raster"])):
            with self.assertRaisesRegex(ValueError, "no reduce"):
                tools.run_tool(scope, "compress", {})
        self.assertEqual(self.inbox.registered, [])
        self.assertEqual(list((self.tools_root / "compressed").glob("*.pdf")), [])

    def test_engine_and_registration_failures_surface_and_keep_source(self):
        scope = self.scope("expedient")
        with patch.object(pdf, "rotate_pdf_pages", side_effect=RuntimeError("motor caído")):
            with self.assertRaisesRegex(RuntimeError, "motor caído"):
                tools.run_tool(scope, "rotate", {"pages": "1", "degrees": "90"})
        with patch.object(inbox_tools, "import_file_to_inbox", side_effect=OSError("disco lleno")):
            with self.assertRaisesRegex(OSError, "disco lleno"):
                tools.run_tool(scope, "extract", {"pages": "1"})
        self.assertEqual(self.inbox.registered, [])


class ScopeAndValidationTests(Dv23ToolsBase):
    def test_expedient_scope_rejects_paths_outside_the_folder(self):
        for path in (self.foreign, self.exp_root / ".." / "ajeno" / "ajeno.pdf"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(tools.ToolScopeError, "no pertenece"):
                    tools.expedient_scope(42, path)
        with self.assertRaisesRegex(tools.ToolScopeError, "solo están disponibles"):
            tools.expedient_scope(42, self.exp_root / "nota.txt")
        with self.assertRaisesRegex(tools.ToolScopeError, "no existe"):
            tools.expedient_scope(42, self.exp_root / "falta.pdf")
        with self.assertRaisesRegex(tools.ToolScopeError, "carpeta vinculada"):
            tools.expedient_scope(7, self.exp_source)
        with self.assertRaisesRegex(tools.ToolScopeError, "expediente guardado"):
            tools.expedient_scope(None, self.exp_source)

    def test_inbox_scope_requires_registered_matching_pdf(self):
        with self.assertRaisesRegex(tools.ToolScopeError, "no está registrado"):
            tools.inbox_scope(55, self.inbox_source)
        with self.assertRaisesRegex(tools.ToolScopeError, "ya no coincide"):
            tools.inbox_scope(1, self.inbox_other)
        with self.assertRaisesRegex(tools.ToolScopeError, "solo están disponibles"):
            tools.inbox_scope(4)

    def test_merge_candidates_stay_inside_the_context(self):
        inbox = self.scope("inbox")
        self.assertEqual([c["item_id"] for c in inbox.merge_candidates], [2])  # not 3 (other expediente) nor 4 (png)
        expedient = self.scope("expedient")
        self.assertEqual([Path(c["path"]) for c in expedient.merge_candidates], [self.exp_other.resolve()])

    def test_merge_refuses_foreign_duplicate_or_single_sources(self):
        scope = self.scope("expedient")
        key = scope.merge_candidates[0]["key"]
        for order, message in (
            (["current", f"expedient:{self.foreign}"], "ya no está disponible"),
            (["current", "inbox:2"], "ya no está disponible"),
            (["current", key, key], "repetido"),
            (["current"], "al menos otro"),
        ):
            with self.subTest(order=order):
                with self.assertRaisesRegex(ValueError, message):
                    tools.run_tool(scope, "merge", {"order": order})
        inbox = self.scope("inbox")
        with self.assertRaisesRegex(ValueError, "ya no está disponible"):
            tools.run_tool(inbox, "merge", {"order": ["current", "inbox:3"]},
                           inbox_items=self.inbox.items.values())
        self.assertEqual(self.inbox.registered, [])
        self.assertFalse(self.tools_root.exists() and any(self.tools_root.rglob("*.pdf")))

    def test_invalid_parameters_are_reported_without_outputs(self):
        scope = self.scope("expedient")
        cases = [
            ("rotate", {"pages": "9", "degrees": "90"}, "fuera de rango"),
            ("rotate", {"pages": "a-b", "degrees": "90"}, "Formato de páginas"),
            ("rotate", {"pages": "1", "degrees": "45"}, "90, 180 o 270"),
            ("move_page", {"page_number": "", "target_position": "1"}, "Página a mover"),
            ("move_page", {"page_number": "1", "target_position": "8"}, "fuera de rango"),
            ("split", {"ranges": "3-1"}, "fuera de límites"),
            ("split", {"ranges": "x"}, "Formato de rangos"),
            ("extract", {"pages": ""}, "al menos una página"),
            ("annotate", {"page_number": "2", "text": "   "}, "texto de la nota"),
            ("annotate", {"page_number": "6", "text": "hola"}, "fuera de rango"),
            ("annotate", {"page_number": "1", "text": "x" * 1001}, "1000"),
            ("annotate", {"page_number": "1", "text": "hola", "position": "left"}, "posición"),
        ]
        for operation, params, message in cases:
            with self.subTest(operation=operation, params=params):
                with self.assertRaisesRegex(ValueError, message):
                    tools.run_tool(scope, operation, params)
        with self.assertRaisesRegex(ValueError, "no soportada"):
            tools.run_tool(scope, "delete", {})
        self.assertEqual(self.inbox.registered, [])

    def test_changed_source_after_form_opened_is_refused(self):
        scope = self.scope("inbox")
        self.inbox_source.write_bytes(self.inbox_source.read_bytes() + b"\n% edited")
        self.hashes[self.inbox_source] = sha256(self.inbox_source)
        with self.assertRaisesRegex(ValueError, "ha cambiado"):
            tools.run_tool(scope, "rotate", PARAMS["rotate"])
        # Re-registered under another path: also refused.
        scope = self.scope("inbox")
        self.inbox.items[1]["stored_path"] = str(self.inbox_other)
        with self.assertRaisesRegex(ValueError, "ya no coincide"):
            tools.run_tool(scope, "rotate", PARAMS["rotate"])
        self.assertEqual(self.inbox.registered, [])

    def test_single_page_and_missing_candidates_disable_with_reasons(self):
        single = make_pdf(self.exp_root / "una.pdf", "UNA", pages=1)
        self.hashes[single] = sha256(single)
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))
        reasons = tools.availability(tools.expedient_scope(42, single))
        self.assertEqual({op for op, reason in reasons.items() if reason}, {"move_page", "split", "extract"})
        self.assertIn("una sola página", reasons["split"])
        lonely = tools.availability(tools.inbox_scope(1, inbox_items=[]))
        self.assertIn("No hay otros PDF", lonely["merge"])
        self.assertEqual([op for op, reason in lonely.items() if reason], ["merge"])

    def test_encrypted_pdf_is_not_processable(self):
        locked = self.exp_root / "cifrado.pdf"
        with fitz.open() as doc:
            doc.new_page()
            doc.save(locked, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
        self.hashes[locked] = sha256(locked)
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))
        with self.assertRaisesRegex(tools.ToolScopeError, "cifrado"):
            tools.expedient_scope(42, locked)


class ViewerUiTests(Dv23ToolsBase):
    def open_viewer(self, context, path=None):
        self.tools_ui = ViewerPdfTools(self.page, on_done=self.done, on_error=self.error,
                                       inbox_items=lambda: list(self.inbox.items.values()))
        if context == "inbox":
            toolbar = self.tools_ui.inbox_toolbar(lambda request: self.inbox.items.get(1))
            return open_document_viewer_modal(self.page, str(path or self.inbox_source),
                                              toolbar_actions=toolbar)
        return open_document_viewer_modal(self.page, str(path or self.exp_source), expediente_id=42,
                                          toolbar_actions=self.tools_ui.expedient_toolbar(42))

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def top_form(self):
        data = self.page.stack[-1].data
        return data if isinstance(data, PdfToolForm) else None

    def fill_and_submit(self, form, operation):
        if operation == "merge":
            key = form.scope.merge_candidates[0]["key"]
            form.checks[key].on_change(None)
            form.move(key, -1)
            self.assertEqual(form.order, [key, "current"])
        else:
            for name, value in PARAMS[operation].items():
                form.fields[name].value = value
        form.submit_button.on_click(None)

    def test_seven_tools_open_forms_run_and_report_in_both_contexts(self):
        for context in ("inbox", "expedient"):
            dialog = self.open_viewer(context)
            for operation in tools.OPERATIONS:
                with self.subTest(context=context, operation=operation):
                    self.done.reset_mock()
                    tool = self.button(dialog, LABELS[operation])
                    self.assertFalse(tool.disabled, tool.tooltip)
                    self.assertEqual(tool.tooltip, adapter.ENABLED_TOOLTIP)
                    tool.on_click(None)
                    form = self.top_form()
                    self.assertIsNotNone(form, "the tool must open its form above the viewer")
                    self.assertIs(self.page.stack[-2], dialog)
                    self.fill_and_submit(form, operation)
                    self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
                    self.assertIn("Original intacto", form.status.value)
                    self.assertFalse(form.submit_button.visible)
                    self.done.assert_called_once()
                    self.check_output(operation, context, self.done.call_args.args[0])
                    form.cancel_button.on_click(None)
                    self.assertIs(self.page.stack[-1], dialog)
                    self.assertTrue(dialog.open)
            self.assertEqual(self.tools_ui.forms, [])
            self.button(dialog, "Cerrar").on_click(None)
            self.assertEqual(self.page.stack, [])
        self.error.assert_not_called()

    def test_errors_stay_visible_in_the_form_and_allow_retry(self):
        dialog = self.open_viewer("expedient")
        self.button(dialog, "Extraer páginas").on_click(None)
        form = self.top_form()
        form.fields["pages"].value = "99"
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("fuera de rango", form.status.value)
        self.assertFalse(form.submit_button.disabled)
        self.done.assert_not_called()
        with patch.object(pdf, "extract_pdf_pages", side_effect=RuntimeError("fallo del motor")):
            form.fields["pages"].value = "1"
            form.submit_button.on_click(None)
        self.assertIn("fallo del motor", form.status.value)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS)
        self.assertEqual(len(self.inbox.registered), 1)

    def test_cancel_and_double_submit_create_at_most_one_copy(self):
        dialog = self.open_viewer("inbox")
        self.button(dialog, "Rotar páginas").on_click(None)
        form = self.top_form()
        form.fields["pages"].value = "1"
        form.cancel_button.on_click(None)
        form.submit_button.on_click(None)  # inert after close
        self.assertIs(self.page.stack[-1], dialog)
        self.assertEqual(self.inbox.registered, [])
        self.assertFalse(self.tools_root.exists() and any(self.tools_root.rglob("*.pdf")))
        self.button(dialog, "Rotar páginas").on_click(None)
        form = self.top_form()
        form.fields["pages"].value = "1"
        form.submit_button.on_click(None)
        form.submit_button.on_click(None)
        self.assertEqual(len(self.inbox.registered), 1)
        self.done.assert_called_once()

    def test_stale_tool_buttons_are_inert_after_navigation_and_close(self):
        dialog = self.open_viewer("expedient")
        stale = self.button(dialog, "Anotar PDF")
        self.button(dialog, "Siguiente").on_click(None)
        stale.on_click(None)
        self.assertIsNone(self.top_form())
        current = self.button(dialog, "Anotar PDF")
        current.on_click(None)
        form = self.top_form()
        self.assertEqual(form.fields["page_number"].value, "2")  # follows the shown page
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        current.on_click(None)
        self.assertEqual(self.page.stack, [])
        self.error.assert_not_called()

    def test_source_changed_while_form_open_is_refused_visibly(self):
        dialog = self.open_viewer("expedient")
        self.button(dialog, "Comprimir PDF").on_click(None)
        form = self.top_form()
        self.exp_source.write_bytes(self.exp_source.read_bytes() + b"\n% edited")
        self.hashes[self.exp_source] = sha256(self.exp_source)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("ha cambiado", form.status.value)
        self.assertEqual(self.inbox.registered, [])

    def test_disabled_tools_explain_the_real_reason(self):
        single = make_pdf(self.exp_root / "una.pdf", "UNA", pages=1)
        self.hashes[single] = sha256(single)
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))
        dialog = self.open_viewer("expedient", single)
        for operation in ("move_page", "split", "extract"):
            tool = self.button(dialog, LABELS[operation])
            self.assertTrue(tool.disabled)
            self.assertIsNone(tool.on_click)
            self.assertIn("una sola página", tool.tooltip)
        self.assertFalse(self.button(dialog, "Anotar PDF").disabled)
        self.button(dialog, "Cerrar").on_click(None)

        # Outside the expediente folder the viewer refuses the preview, so no tools
        # are offered; the factory itself also disables all seven with the reason.
        dialog = self.open_viewer("expedient", self.foreign)
        self.assertEqual([b for b in viewer_action_buttons(dialog) if b.data in LABELS], [])
        self.button(dialog, "Cerrar").on_click(None)
        from backend.services.document_preview_session import PreviewRequest
        controls = self.tools_ui.expedient_toolbar(42)(PreviewRequest(str(self.foreign), 42, 1, 1.6))
        self.assertEqual(len(controls), 7)
        self.assertTrue(all(c.disabled and c.on_click is None and "no pertenece" in c.tooltip
                            for c in controls))

        image = self.exp_root / "foto.png"
        fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5, 5), False).save(image)
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))
        dialog = self.open_viewer("expedient", image)
        self.assertTrue(all(b.disabled and b.tooltip == adapter.NOT_PDF
                            for b in viewer_action_buttons(dialog) if b.data in LABELS))
        self.button(dialog, "Cerrar").on_click(None)

        with patch.object(pdf, "PdfReader", None):
            dialog = self.open_viewer("inbox")
            self.assertTrue(all(b.disabled and b.tooltip == adapter.NO_PYPDF
                                for b in viewer_action_buttons(dialog) if b.data in LABELS))
            self.button(dialog, "Cerrar").on_click(None)

        del self.inbox.items[2]  # no other PDF with the same link left
        dialog = self.open_viewer("inbox")
        merge = self.button(dialog, "Unir PDFs")
        self.assertTrue(merge.disabled)
        self.assertIn("No hay otros PDF", merge.tooltip)
        self.button(dialog, "Cerrar").on_click(None)

    def test_click_time_scope_failure_is_reported_above_the_viewer(self):
        dialog = self.open_viewer("inbox")
        rotate = self.button(dialog, "Rotar páginas")
        self.inbox.items[1]["stored_path"] = str(self.inbox_other)
        rotate.on_click(None)
        notice = self.page.stack[-1]
        self.assertIsNot(notice, dialog)
        self.assertIn("ya no coincide", notice.content.value)
        self.error.assert_called_once()
        notice.actions[0].on_click(None)
        self.assertIs(self.page.stack[-1], dialog)
        self.assertEqual(self.tools_ui.notices, [])

    def test_overlay_fallback_page_leaves_no_orphan_forms(self):
        self.page = SimpleNamespace(overlay=[], update=Mock())
        dialog = self.open_viewer("expedient")
        self.button(dialog, "Dividir PDF").on_click(None)
        form = self.page.overlay[-1].data
        self.assertIsInstance(form, PdfToolForm)
        form.close()
        self.assertEqual(self.page.overlay, [dialog])
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.page.overlay, [])

    def test_toolbar_scope_is_cached_while_scrolling(self):
        dialog = self.open_viewer("expedient")
        with patch.object(tools, "expedient_scope", wraps=tools.expedient_scope) as build:
            for _ in range(3):
                self.button(dialog, "Siguiente").on_click(None)
            build.assert_not_called()
        self.button(dialog, "Cerrar").on_click(None)


def bind(path, names, scope):
    """Execute the real view closures at module level; free names come from scope."""
    found = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            found.setdefault(node.name, []).append(node)
    assert all(len(found.get(name, ())) == 1 for name in names), sorted(found)
    module = ast.Module(body=[found[name][0] for name in names], type_ignores=[])
    exec(compile(module, f"<{path.name}>", "exec"), scope)
    return scope


class RealViewWiringTests(Dv23ToolsBase):
    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def test_expedientes_preview_runs_a_tool_end_to_end(self):
        viewer_dialog = ft.AlertDialog(modal=True)
        self.page.overlay.append(viewer_dialog)
        form_error = Mock()
        scope = bind(EXPEDIENTS, ("show_document_preview",), dict(
            page=self.page, state={"dialog_expediente_id": 42}, show_form_error=form_error,
            open_document_viewer_modal=open_document_viewer_modal,
            document_viewer_dialog=viewer_dialog,
        ))
        dialog = scope["show_document_preview"](str(self.exp_source))
        self.assertIs(dialog, viewer_dialog)
        self.button(dialog, "Mover página").on_click(None)
        form = self.page.stack[-1].data
        form.fields["page_number"].value = "5"
        form.fields["target_position"].value = "1"
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        self.assertEqual(page_markers(form.outcome["outputs"][0])[0], "EXP-P5")
        self.assertEqual(self.inbox.registered[0]["metadata_json"]["provenance"]["expediente_id"], 42)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        form_error.assert_not_called()

    def test_bandeja_preview_runs_a_tool_and_refreshes_listing(self):
        state = {"selected_item_id": 1, "selected_item_ids": {1}, "items": list(self.inbox.items.values())}
        refresh, batch, show_error = Mock(), Mock(), Mock()
        scope = bind(INBOX, ("selected_item", "after_viewer_pdf_tool", "pdf_toolbar_for_item",
                             "inbox_viewer_options", "show_preview"), dict(
            page=self.page, state=state, open_document_viewer_modal=open_document_viewer_modal,
            ViewerPdfTools=ViewerPdfTools,
            document_inbox_service=SimpleNamespace(get_inbox_item=self.inbox.get),
            refresh_items=refresh, _document_tool_register_response_in_batch_if_needed=batch,
            show_error=show_error,
        ))
        scope["show_preview"]()
        dialog = self.page.stack[-1]
        self.button(dialog, "Unir PDFs").on_click(None)
        form = self.page.stack[-1].data
        self.assertEqual([c["item_id"] for c in form.scope.merge_candidates], [2])
        form.checks["inbox:2"].on_change(None)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        refresh.assert_called_once_with()
        batch.assert_called_once()
        self.assertEqual(batch.call_args.args[0]["generated_item"]["id"], 100)
        self.assertIn("#100", form.status.value)
        self.assertEqual(page_markers(form.outcome["outputs"][0])[:2], ["INB-P1", "INB-P2"])
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        show_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
