"""WO-DV29-02: the six JPG/PNG tools in the viewer, from Bandeja and Expedientes.

Synthetic images and PDFs in a TemporaryDirectory only. The Bandeja registry
is an in-memory fake behind the real document-tools services; no database,
no network, no Box, no expediente folders other than the temporary one.
"""
import ast
import hashlib
import random
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft
from PIL import Image

from backend.services import document_viewer_service as viewer_service
from backend.services.document_preview_session import PreviewRequest
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools import document_viewer_image_tools_service as tools
from backend.services.document_tools import image_tools_service as image_tools
from backend.services.document_tools import safe_file_service
from backend.services.document_tools.document_tool_result import DocumentToolResult
from frontend.components import document_viewer_modal as viewer
from frontend.components import document_viewer_multidoc as multidoc
from frontend.components import pdf_tools_toolbar_adapter as adapter
from frontend.components.document_viewer_image_tools import (
    NO_EXPEDIENT, NOT_IMAGE, ExpedientImageToolbar, ImageToolForm, InboxImageToolbar,
    ViewerImageTools,
)
from frontend.components.document_viewer_modal import (
    IMAGE_TOOLS_LABEL, TOOLS_LABEL, open_document_viewer_modal, viewer_action_buttons,
    viewer_action_label, viewer_active_document, viewer_layout,
)
from frontend.components.document_viewer_pdf_tools import (
    PdfToolForm, Q_ERROR, Q_SUCCESS, ViewerPdfTools,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPEDIENTS = REPO_ROOT / "frontend" / "views" / "expedients_view.py"
INBOX = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"

PDF_LABELS = dict(adapter.PDF_ACTIONS)
IMAGE_DATA = ["image_rotate", "image_crop", "image_resize", "image_optimize", "image_convert", "image_to_pdf"]
JPG_LABELS = ["Rotar", "Recortar", "Redimensionar", "Optimizar", "Convertir a PNG", "Convertir a PDF"]
PNG_LABELS = JPG_LABELS[:4] + ["Convertir a JPG", "Convertir a PDF"]
IMAGE_TITLE = "EDICIÓN Y PROCESAMIENTO DE IMAGEN"
PDF_TITLE = "EDICIÓN Y PROCESAMIENTO DEL PDF"

# Parameters for the 64x48 JPG of both contexts.
PARAMS = {
    "rotate": {"degrees": "90"},
    "crop": {"left": "4", "top": "2", "right": "14", "bottom": "12"},
    "resize": {"width": "32"},
    "optimize": {"quality": "40"},
    "convert": {},
    "to_pdf": {},
}
LABEL_OF = dict(zip(tools.OPERATIONS, ("Recortar", "Rotar", "Redimensionar", "Optimizar",
                                       "Convertir a PNG", "Convertir a PDF")))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def noise(size, seed=1):
    w, h = size
    return Image.frombytes("RGB", size, random.Random(seed).randbytes(w * h * 3))


def save_jpeg(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=95)
    return path


def save_png(path, size=(40, 20)):
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste((0, 128, 255, 255), (w // 2, 0, w, h))
    img.save(path, "PNG", compress_level=0)
    return path


def make_pdf(path, label, pages=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as doc:
        for index in range(pages):
            doc.new_page(width=200, height=200).insert_text((10, 20), f"{label}-P{index + 1}", fontsize=9)
        doc.save(path)
    return path


def walk(control):
    yield control
    for name in ("content", "title"):
        child = getattr(control, name, None)
        if isinstance(child, ft.Control):
            yield from walk(child)
    for child in getattr(control, "controls", None) or ():
        yield from walk(child)


def toolbar_texts(dialog):
    return [c.value for row in dialog.actions for c in walk(row) if isinstance(c, ft.Text)]


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


class Dv29UiBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.tools_root = self.tmp / "tools"

        # Expediente folder (temporary) and Bandeja originals.
        self.exp_root = self.tmp / "expediente_42"
        self.exp_jpg = save_jpeg(noise((64, 48)), self.exp_root / "fotos" / "foto.jpg")
        self.exp_png = save_png(self.exp_root / "plano.png")
        self.exp_pdf = make_pdf(self.exp_root / "contrato.pdf", "EXP")
        Image.new("RGB", (8, 8), (255, 0, 0)).save(self.exp_root / "animada.gif", "GIF")
        self.inbox = FakeInbox()
        self.inbox_jpg = save_jpeg(noise((64, 48), 3), self.tmp / "inbox" / "a.jpg")
        self.inbox_png = save_png(self.tmp / "inbox" / "c.png")
        self.inbox_pdf = make_pdf(self.tmp / "inbox" / "d.pdf", "INB")
        self.inbox_old = save_jpeg(noise((16, 16), 5), self.tmp / "inbox" / "descartada.jpg")
        link = {"client_id": 7, "expedient_id": 42, "status": "pending"}
        self.inbox.items = {
            1: {"id": 1, "stored_path": str(self.inbox_jpg), "original_filename": "a.jpg", **link},
            3: {"id": 3, "stored_path": str(self.inbox_png), "original_filename": "c.png", **link},
            4: {"id": 4, "stored_path": str(self.inbox_pdf), "original_filename": "d.pdf", **link},
            6: {"id": 6, "stored_path": str(self.inbox_old), "original_filename": "descartada.jpg",
                **dict(link, status="discarded")},
        }

        self.hashes = {path: sha256(path) for path in self.tmp.rglob("*") if path.is_file()}
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))

        for target, attribute, value in (
            (safe_file_service, "DOCUMENT_TOOLS_ROOT", self.tools_root),
            (viewer_service, "PREVIEW_DIR", self.tmp / "previews"),
            (viewer_service, "get_expediente_document_root", Mock(side_effect=self.expediente_root)),
            (inbox_tools, "get_inbox_item", self.inbox.get),
            (inbox_tools, "import_file_to_inbox", self.inbox.register),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The fold preference is session-wide; every test starts unfolded.
        patcher = patch.dict(viewer._TOOLS_PREFERENCE, {"collapsed": False})
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

    def toolbar(self, context):
        self.pdf_ui = ViewerPdfTools(self.page, on_done=self.done, on_error=self.error,
                                     inbox_items=lambda: list(self.inbox.items.values()))
        self.image_ui = ViewerImageTools(self.page, on_done=self.done, on_error=self.error)
        if context == "inbox":
            ids = {item["stored_path"]: item_id for item_id, item in self.inbox.items.items()}

            def resolve(request):
                return self.inbox.items.get(ids.get(str(request.path)))
            return self.pdf_ui.inbox_toolbar(resolve).with_image_tools(self.image_ui.inbox_toolbar(resolve))
        return self.pdf_ui.expedient_toolbar(42).with_image_tools(self.image_ui.expedient_toolbar(42))

    def open_viewer(self, context, path, queue=None, index=0):
        return open_document_viewer_modal(
            self.page, str(path), title=Path(path).name, expediente_id=None if context == "inbox" else 42,
            toolbar_actions=self.toolbar(context), near_window=0,
            queue=[{"path": str(p), "name": Path(p).name} for p in queue] if queue else None,
            queue_index=index)

    def jpg(self, context):
        return self.inbox_jpg if context == "inbox" else self.exp_jpg

    def png(self, context):
        return self.inbox_png if context == "inbox" else self.exp_png

    def pdf(self, context):
        return self.inbox_pdf if context == "inbox" else self.exp_pdf

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def image_buttons(self, dialog):
        return [b for b in viewer_action_buttons(dialog) if str(b.data or "").startswith("image_")]

    def pdf_buttons(self, dialog):
        return [b for b in viewer_action_buttons(dialog) if b.data in PDF_LABELS]

    def top_form(self):
        data = self.page.stack[-1].data if self.page.stack else None
        return data if isinstance(data, PdfToolForm) else None

    def submit(self, form, params):
        for name, value in params.items():
            form.fields[name].value = value
        form.submit_button.on_click(None)

    def check_output(self, operation, context, outcome, source_size=(64, 48)):
        outputs = [Path(p) for p in outcome["outputs"]]
        self.assertEqual(len(outputs), 1)
        output = outputs[0]
        self.assertTrue(output.is_file())
        self.assertTrue(output.resolve().is_relative_to(self.tools_root.resolve()), output)
        if operation == "to_pdf":
            self.assertEqual(output.suffix, ".pdf")
            with fitz.open(output) as doc:
                self.assertEqual(doc.page_count, 1)
        else:
            with Image.open(output) as img:
                size, fmt = img.size, img.format
            expected = {"rotate": source_size[::-1], "crop": (10, 10), "resize": (32, 24)}.get(operation)
            if expected:
                self.assertEqual(size, expected)
            if operation == "convert":
                self.assertEqual(fmt, "PNG")
            if operation == "optimize":
                self.assertLess(output.stat().st_size, self.jpg(context).stat().st_size)
        item = outcome["generated_items"][0]
        self.assertEqual(item["source_type"], "generated")
        metadata = item["metadata_json"]
        if context == "inbox":
            self.assertEqual(metadata["source_item_ids"], [1])
        else:
            self.assertEqual(metadata["provenance"]["source_context"], "expedient")
            self.assertEqual(metadata["provenance"]["expediente_id"], 42)
            self.assertEqual(metadata["provenance"]["source_relative_path"], str(Path("fotos/foto.jpg")))


class ToolbarAvailabilityTests(Dv29UiBase):
    def test_jpg_and_png_show_six_image_tools_in_both_contexts(self):
        for context in ("inbox", "expedient"):
            for path, labels in ((self.jpg(context), JPG_LABELS), (self.png(context), PNG_LABELS)):
                with self.subTest(context=context, path=path.name):
                    dialog = self.open_viewer(context, path)
                    tools_ = self.image_buttons(dialog)
                    self.assertEqual([b.data for b in tools_], IMAGE_DATA)
                    self.assertEqual([viewer_action_label(b) for b in tools_], labels)
                    for tool in tools_:
                        self.assertFalse(tool.disabled, tool.tooltip)
                        self.assertEqual(tool.tooltip, adapter.ENABLED_TOOLTIP)
                        icon = next(c for c in walk(tool) if isinstance(c, ft.Icon))
                        self.assertEqual(icon.icon, viewer._TOOL_ICONS[tool.data])
                    self.assertEqual(self.pdf_buttons(dialog), [])
                    self.assertIn(IMAGE_TITLE, toolbar_texts(dialog))
                    self.assertNotIn(PDF_TITLE, toolbar_texts(dialog))
                    self.assertTrue(viewer_layout(dialog).tools_toggle.tooltip.startswith(IMAGE_TOOLS_LABEL))
                    self.button(dialog, "Cerrar").on_click(None)
                    self.assertEqual(self.page.stack, [])
        self.error.assert_not_called()

    def test_pdf_keeps_its_seven_tools_labels_icons_and_title(self):
        for context in ("inbox", "expedient"):
            with self.subTest(context=context):
                dialog = self.open_viewer(context, self.pdf(context))
                tools_ = self.pdf_buttons(dialog)
                self.assertEqual([b.data for b in tools_], [op for op, _ in adapter.PDF_ACTIONS])
                self.assertEqual([viewer_action_label(b) for b in tools_], [l for _, l in adapter.PDF_ACTIONS])
                # Still the first commands of the viewer, as in DV23.
                self.assertTrue(all(a is b for a, b in zip(viewer_action_buttons(dialog)[:7], tools_)))
                for tool in tools_:
                    icon = next(c for c in walk(tool) if isinstance(c, ft.Icon))
                    self.assertEqual(icon.icon, viewer._TOOL_ICONS[tool.data])
                self.assertEqual(self.image_buttons(dialog), [])
                self.assertIn(PDF_TITLE, toolbar_texts(dialog))
                self.assertTrue(viewer_layout(dialog).tools_toggle.tooltip.startswith(TOOLS_LABEL))
                self.button(dialog, "Rotar páginas").on_click(None)
                self.assertIsInstance(self.top_form(), PdfToolForm)
                self.assertNotIsInstance(self.top_form(), ImageToolForm)
                self.top_form().close()
                self.button(dialog, "Cerrar").on_click(None)
        self.error.assert_not_called()

    def test_unavailable_documents_explain_the_reason(self):
        expedient = self.toolbar("expedient")
        # Other image formats: the six commands, disabled with the real reason.
        controls = expedient(PreviewRequest(str(self.exp_root / "animada.gif"), 42, 1, 1.6))
        self.assertEqual([c.data for c in controls], IMAGE_DATA)
        self.assertTrue(all(c.disabled and c.on_click is None and c.tooltip == NOT_IMAGE for c in controls))
        self.assertEqual(expedient.tools_kind(str(self.exp_root / "animada.gif")), "image")
        # Non-image, non-PDF documents keep the PDF commands and their reason.
        controls = expedient(PreviewRequest(str(self.exp_root / "nota.docx"), 42, 1, 1.6))
        self.assertEqual(len(controls), 7)
        self.assertTrue(all(c.disabled and c.tooltip == adapter.NOT_PDF for c in controls))
        self.assertEqual(expedient.tools_kind("nota.docx"), "pdf")
        # Images outside the expediente folder or without expediente.
        controls = expedient(PreviewRequest(str(self.inbox_jpg), 42, 1, 1.6))
        self.assertTrue(all(c.disabled and "no pertenece" in c.tooltip for c in controls))
        orphan = ViewerImageTools(self.page).expedient_toolbar(None)
        self.assertTrue(all(c.tooltip == NO_EXPEDIENT
                            for c in orphan(PreviewRequest(str(self.exp_jpg), None, 1, 1.6))))
        # Bandeja: discarded or unregistered images; content not matching the extension.
        inbox = self.toolbar("inbox")
        controls = inbox(PreviewRequest(str(self.inbox_old), None, 1, 1.6))
        self.assertTrue(all(c.disabled and "discarded" in c.tooltip for c in controls))
        controls = inbox(PreviewRequest(str(self.exp_jpg), None, 1, 1.6))
        self.assertTrue(all(c.disabled and "no está registrado" in c.tooltip for c in controls))
        fake = self.tmp / "inbox" / "falso.png"
        save_jpeg(noise((8, 8)), self.tmp / "inbox" / "tmp.jpg").rename(fake)
        self.inbox.items[9] = {"id": 9, "stored_path": str(fake), "original_filename": "falso.png",
                               "status": "pending"}
        inbox = self.toolbar("inbox")
        controls = inbox(PreviewRequest(str(fake), None, 1, 1.6))
        self.assertTrue(all(c.disabled and "no coincide" in c.tooltip for c in controls))
        self.assertEqual(self.inbox.registered, [])

    def test_factories_keep_their_pdf_contract_types(self):
        inbox, expedient = self.toolbar("inbox"), self.toolbar("expedient")
        self.assertIsInstance(inbox, adapter.PdfToolsToolbarAdapter)
        self.assertIsInstance(inbox.image_tools, InboxImageToolbar)
        self.assertIsInstance(expedient, adapter.ExpedientPdfToolsToolbar)
        self.assertIsInstance(expedient.image_tools, ExpedientImageToolbar)
        self.assertEqual(expedient.expediente_id, 42)
        # Without a companion, a PNG keeps the DV23 PDF behaviour.
        alone = ViewerPdfTools(self.page).expedient_toolbar(42)
        controls = alone(PreviewRequest(str(self.exp_png), 42, 1, 1.6))
        self.assertEqual(len(controls), 7)
        self.assertTrue(all(c.tooltip == adapter.NOT_PDF for c in controls))
        self.assertEqual(alone.tools_kind(str(self.exp_png)), "pdf")


class FormTests(Dv29UiBase):
    def test_six_tools_run_end_to_end_in_both_contexts(self):
        for context in ("inbox", "expedient"):
            dialog = self.open_viewer(context, self.jpg(context))
            for operation in tools.OPERATIONS:
                with self.subTest(context=context, operation=operation):
                    self.done.reset_mock()
                    self.button(dialog, LABEL_OF[operation]).on_click(None)
                    form = self.top_form()
                    self.assertIsInstance(form, ImageToolForm)
                    self.assertIs(self.page.stack[-2], dialog)
                    self.assertEqual(form.operation, operation)
                    self.submit(form, PARAMS[operation])
                    self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
                    self.assertIn("Original intacto", form.status.value)
                    self.assertIn(f"#{self.inbox.registered[-1]['id']}", form.status.value)
                    self.assertFalse(form.submit_button.visible)
                    self.done.assert_called_once()
                    self.check_output(operation, context, self.done.call_args.args[0])
                    form.cancel_button.on_click(None)
                    self.assertIs(self.page.stack[-1], dialog)
                    self.assertTrue(dialog.open)
            self.assertEqual(self.image_ui.forms, [])
            self.button(dialog, "Cerrar").on_click(None)
            self.assertEqual(self.page.stack, [])
        self.assertEqual(len(self.inbox.registered), 12)
        self.error.assert_not_called()

    def test_png_tools_from_the_viewer(self):
        dialog = self.open_viewer("expedient", self.exp_png)
        for label, params, check in (
            # The transparent half is flattened on white.
            ("Convertir a JPG", {}, lambda img: (img.format, img.size) == ("JPEG", (40, 20))
             and all(v >= 245 for v in img.getpixel((2, 2)))),
            ("Optimizar", {}, lambda img: img.format == "PNG" and img.mode == "RGBA"),
            ("Recortar", {"left": "20", "top": "0", "right": "40", "bottom": "20"},
             lambda img: img.size == (20, 20)),
        ):
            with self.subTest(label=label):
                self.button(dialog, label).on_click(None)
                form = self.top_form()
                self.submit(form, params)
                self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
                with Image.open(form.outcome["outputs"][0]) as img:
                    self.assertTrue(check(img), label)
                form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_forms_show_original_and_format_dependent_options(self):
        dialog = self.open_viewer("inbox", self.inbox_jpg)
        self.button(dialog, "Optimizar").on_click(None)
        form = self.top_form()
        texts = [c.value for c in walk(form.dialog.content) if isinstance(c, ft.Text)]
        original = next(text for text in texts if text.startswith("Original:"))
        self.assertRegex(original, r"^Original: JPG · 64 × 48 px · [\d,]+ (B|KB)$")
        self.assertIn("la imagen original no se modifica", " ".join(texts))
        self.assertEqual(form.fields["quality"].value, str(image_tools.DEFAULT_JPEG_QUALITY))
        self.assertIn("no se crea ningún archivo", form.preview.value)
        form.close()
        self.button(dialog, "Convertir a PNG").on_click(None)
        self.assertEqual(self.top_form().params(), {"target_format": "png"})
        self.top_form().close()
        self.button(dialog, "Cerrar").on_click(None)

        dialog = self.open_viewer("inbox", self.inbox_png)
        self.button(dialog, "Optimizar").on_click(None)
        form = self.top_form()
        self.assertNotIn("quality", form.fields)  # PNG: lossless, no quality
        texts = " ".join(c.value for c in walk(form.dialog.content) if isinstance(c, ft.Text))
        self.assertIn("sin pérdida", texts)
        self.assertIn("con transparencia", texts)
        form.close()
        self.button(dialog, "Convertir a JPG").on_click(None)
        form = self.top_form()
        self.assertEqual(form.params(), {"target_format": "jpg"})
        self.assertIn("#FFFFFF", form.preview.value)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.inbox.registered, [])

    def test_preview_explains_the_result_as_parameters_change(self):
        dialog = self.open_viewer("expedient", self.exp_jpg)
        self.button(dialog, "Redimensionar").on_click(None)
        form = self.top_form()
        self.assertIn("Indica el ancho", form.preview.value)
        form.fields["width"].value = "32"
        form.fields["width"].on_change(None)
        self.assertEqual(form.preview.value, "Resultado: 32 × 24 px.")
        form.fields["height"].value = "12"
        form.fields["height"].on_change(None)
        self.assertEqual(form.preview.value, "Resultado: 16 × 12 px.")
        form.close()

        self.button(dialog, "Rotar").on_click(None)
        form = self.top_form()
        self.assertEqual(form.preview.value, "Resultado: 48 × 64 px.")
        form.fields["degrees"].value = "180"
        form._changed()
        self.assertEqual(form.preview.value, "Resultado: 64 × 48 px.")
        form.close()

        self.button(dialog, "Recortar").on_click(None)
        form = self.top_form()
        self.assertEqual([form.fields[n].value for n in ("left", "top", "right", "bottom")],
                         ["0", "0", "64", "48"])
        self.assertIn("toda la imagen", form.preview.value)
        form.submit_button.on_click(None)  # whole image: refused, nothing written
        self.assertEqual(form.status.color, Q_ERROR)
        form.fields["right"].value = "99"
        form.fields["right"].on_change(None)
        self.assertIn("Fuera de límites", form.preview.value)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("fuera de límites", form.status.value.lower())
        form.fields["right"].value = "32"
        form.fields["right"].on_change(None)
        self.assertEqual(form.preview.value, "Resultado: 32 × 48 px desde (0, 0).")
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.inbox.registered, [])
        self.assertFalse(self.tools_root.exists() and any(self.tools_root.rglob("*.*")))

    def test_errors_stay_visible_and_allow_retry(self):
        dialog = self.open_viewer("expedient", self.exp_jpg)
        self.button(dialog, "Redimensionar").on_click(None)
        form = self.top_form()
        self.submit(form, {"width": "abc"})
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("número entero", form.status.value)
        self.assertFalse(form.submit_button.disabled)
        self.done.assert_not_called()
        self.submit(form, {"width": "32"})
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        form.close()

        # Optimization never promises a reduction: no smaller copy, visible error.
        failure = DocumentToolResult.failure(
            operation="image_optimize",
            errors=["La optimización no reduce el tamaño del archivo; no se genera copia."])
        self.button(dialog, "Optimizar").on_click(None)
        form = self.top_form()
        with patch.object(image_tools, "optimize_image", return_value=failure):
            form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("no reduce", form.status.value)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        self.assertRegex(form.status.value, r"Tamaño original: .+ · tamaño final: .+ \(-\d+ %\)")
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(len(self.inbox.registered), 2)

    def test_double_click_and_double_submit_create_at_most_one_copy(self):
        dialog = self.open_viewer("inbox", self.inbox_jpg)
        rotate = self.button(dialog, "Rotar")
        rotate.on_click(None)
        rotate.on_click(None)  # a second click reuses the open form
        self.assertEqual(len(self.page.stack), 2)
        form = self.top_form()
        form.cancel_button.on_click(None)
        form.submit_button.on_click(None)  # inert after close
        self.assertIs(self.page.stack[-1], dialog)
        self.assertEqual(self.inbox.registered, [])
        self.button(dialog, "Rotar").on_click(None)
        form = self.top_form()
        form.submit_button.on_click(None)
        form.submit_button.on_click(None)
        self.assertEqual(len(self.inbox.registered), 1)
        self.done.assert_called_once()
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_source_is_revalidated_when_the_form_runs(self):
        dialog = self.open_viewer("expedient", self.exp_jpg)
        self.button(dialog, "Convertir a PDF").on_click(None)
        form = self.top_form()
        self.exp_jpg.write_bytes(self.exp_jpg.read_bytes() + b"\x00editado")
        self.hashes[self.exp_jpg] = sha256(self.exp_jpg)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("ha cambiado", form.status.value)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

        dialog = self.open_viewer("inbox", self.inbox_jpg)
        self.button(dialog, "Rotar").on_click(None)
        form = self.top_form()
        self.inbox.items[1]["status"] = "discarded"
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("discarded", form.status.value)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.inbox.registered, [])

    def test_click_time_failure_is_reported_above_the_viewer(self):
        dialog = self.open_viewer("inbox", self.inbox_jpg)
        rotate = self.button(dialog, "Rotar")
        self.inbox.items[1]["stored_path"] = str(self.inbox_png)
        rotate.on_click(None)
        notice = self.page.stack[-1]
        self.assertIsNot(notice, dialog)
        self.assertEqual(notice.title.value, "Herramientas de imagen")
        self.assertIn("ya no coincide", notice.content.value)
        self.error.assert_called_once()
        notice.actions[0].on_click(None)
        self.assertIs(self.page.stack[-1], dialog)
        self.assertEqual(self.image_ui.notices, [])
        self.button(dialog, "Cerrar").on_click(None)


class QueueAndComparatorTests(Dv29UiBase):
    def test_queue_switches_toolbar_and_stale_commands_are_inert(self):
        queue = [self.exp_jpg, self.exp_pdf, self.exp_png]
        dialog = self.open_viewer("expedient", self.exp_jpg, queue=queue)
        self.assertEqual([viewer_action_label(b) for b in self.image_buttons(dialog)], JPG_LABELS)
        stale = self.button(dialog, "Rotar")
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(viewer_active_document(dialog).path, str(self.exp_pdf))
        self.assertEqual(self.image_buttons(dialog), [])
        self.assertEqual(len(self.pdf_buttons(dialog)), 7)
        self.assertIn(PDF_TITLE, toolbar_texts(dialog))
        stale.on_click(None)
        self.assertIsNone(self.top_form())
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual([viewer_action_label(b) for b in self.image_buttons(dialog)], PNG_LABELS)
        self.assertIn(IMAGE_TITLE, toolbar_texts(dialog))
        current = self.button(dialog, "Convertir a JPG")
        current.on_click(None)
        form = self.top_form()
        self.assertEqual((form.scope.format, form.scope.relative_path), ("PNG", "plano.png"))
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        current.on_click(None)
        self.assertEqual(self.page.stack, [])
        self.assertEqual(self.inbox.registered, [])
        self.error.assert_not_called()

    def test_comparator_toolbar_follows_the_active_document(self):
        queue = [self.inbox_jpg, self.inbox_pdf, self.inbox_png]
        dialog = self.open_viewer("inbox", self.inbox_jpg, queue=queue)
        self.button(dialog, "Comparador 4").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(len(self.image_buttons(dialog)), 6)
        stale = self.button(dialog, "Recortar")
        layout.tiles[1].container.on_click(None)
        self.assertEqual(viewer_active_document(dialog).path, str(self.inbox_pdf))
        self.assertEqual(self.image_buttons(dialog), [])
        self.assertEqual(len(self.pdf_buttons(dialog)), 7)
        stale.on_click(None)
        self.assertIsNone(self.top_form())
        viewer_layout(dialog).tiles[2].container.on_click(None)
        self.assertEqual([viewer_action_label(b) for b in self.image_buttons(dialog)], PNG_LABELS)
        self.button(dialog, "Recortar").on_click(None)
        form = self.top_form()
        self.assertEqual((form.scope.inbox_item_id, form.scope.width, form.scope.height), (3, 40, 20))
        self.submit(form, {"left": "0", "top": "0", "right": "20", "bottom": "20"})
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        self.assertEqual(self.inbox.registered[0]["metadata_json"]["source_item_ids"], [3])
        form.close()
        self.assertIs(self.page.stack[-1], dialog)
        self.assertEqual(viewer_layout(dialog).mode, multidoc.MODE_COMPARE)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.page.stack, [])

    def test_fold_toggle_names_the_active_tools(self):
        dialog = self.open_viewer("expedient", self.exp_jpg, queue=[self.exp_jpg, self.exp_pdf])
        toggle = viewer_layout(dialog).tools_toggle
        self.assertEqual(toggle.tooltip, f"{IMAGE_TOOLS_LABEL} desplegadas: plegar")
        toggle.on_click(None)
        layout = viewer_layout(dialog)
        self.assertTrue(layout.tools_collapsed)
        self.assertEqual(viewer_action_label(layout.tools_toggle), IMAGE_TOOLS_LABEL)
        self.assertEqual(self.image_buttons(dialog), [])
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(viewer_action_label(viewer_layout(dialog).tools_toggle), TOOLS_LABEL)
        viewer_layout(dialog).tools_toggle.on_click(None)
        self.assertEqual(len(self.pdf_buttons(dialog)), 7)
        self.button(dialog, "Cerrar").on_click(None)


class RealViewWiringTests(Dv29UiBase):
    def test_bandeja_preview_runs_an_image_tool_and_refreshes_listing(self):
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
        self.assertEqual(len(self.image_buttons(dialog)), 6)
        self.button(dialog, "Optimizar").on_click(None)
        form = self.top_form()
        self.assertIsInstance(form, ImageToolForm)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        refresh.assert_called_once_with()
        batch.assert_called_once()
        self.assertEqual(batch.call_args.args[0]["generated_item"]["id"], 100)
        self.assertIn("#100", form.status.value)
        form.close()
        self.assertIs(self.page.stack[-1], dialog)
        self.assertTrue(dialog.open)
        self.button(dialog, "Cerrar").on_click(None)
        show_error.assert_not_called()

    def test_expedientes_preview_runs_an_image_tool_end_to_end(self):
        viewer_dialog = ft.AlertDialog(modal=True)
        self.page.overlay.append(viewer_dialog)
        form_error = Mock()
        scope = bind(EXPEDIENTS, ("show_document_preview",), dict(
            page=self.page, state={"dialog_expediente_id": 42}, show_form_error=form_error,
            open_document_viewer_modal=open_document_viewer_modal,
            document_viewer_dialog=viewer_dialog,
        ))
        dialog = scope["show_document_preview"](str(self.exp_jpg))
        self.assertIs(dialog, viewer_dialog)
        self.button(dialog, "Convertir a PNG").on_click(None)
        form = self.top_form()
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        self.assertEqual(Path(form.outcome["outputs"][0]).suffix, ".png")
        self.assertEqual(self.inbox.registered[0]["metadata_json"]["provenance"]["expediente_id"], 42)
        form.close()
        self.assertTrue(dialog.open)
        # The same viewer keeps the PDF tools for PDFs of the folder.
        dialog = scope["show_document_preview"](str(self.exp_pdf))
        self.assertEqual(len(self.pdf_buttons(dialog)), 7)
        self.button(dialog, "Cerrar").on_click(None)
        form_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
