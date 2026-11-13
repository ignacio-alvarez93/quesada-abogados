"""WO-DV29-03: marked JPG/PNG of the viewer comparator -> one multipage PDF.

Synthetic images and PDFs in a TemporaryDirectory only (fixtures of
test_dv29_image_tools_ui). The Bandeja registry is an in-memory fake behind the
real document-tools services; no database, no network, no Box.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft
from PIL import Image

from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools import document_viewer_image_tools_service as tools
from backend.services.document_tools import image_tools_service as image_tools
from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.document_viewer_tools_service import ToolScopeError
from frontend.components import pdf_tools_toolbar_adapter as adapter
from frontend.components.document_viewer_image_tools import (
    MULTI_LABEL, NEED_CONSENT, NO_IMAGE_SELECTION, NOT_IMAGE, ImageToolForm, ImagesToPdfForm,
)
from frontend.components.document_viewer_link_dialog import ViewerLinking
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label, viewer_active_document,
    viewer_layout,
)
from frontend.components.document_viewer_pdf_tools import Q_ERROR, Q_SUCCESS
from scripts.tests import test_dv29_image_tools_ui as ui


MULTI_DATA = "image_" + tools.MULTI_OPERATION


def save_exif_jpeg(path, stored=(30, 20), orientation=6):
    """Stored landscape, displayed portrait once the EXIF orientation is applied."""
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[image_tools.EXIF_ORIENTATION_TAG] = orientation
    ui.noise(stored, 9).save(path, "JPEG", quality=95, exif=exif)
    return path


def resolved(path):
    return str(Path(path).resolve())


def page_sizes(pdf):
    """Page sizes in source pixels (images_to_pdf writes at 100 dpi)."""
    with fitz.open(pdf) as doc:
        return [(round(p.rect.width * 100 / 72), round(p.rect.height * 100 / 72)) for p in doc]


def pdf_pixel(pdf, page, xy):
    with fitz.open(pdf) as doc:
        return doc[page].get_pixmap(dpi=100).pixel(*xy)


class ImagesToPdfBase(ui.Dv29UiBase):
    def setUp(self):
        super().setUp()
        # Extra originals: EXIF-rotated JPG, homonyms and other Bandeja links.
        self.exp_exif = save_exif_jpeg(self.exp_root / "girada.jpg")
        self.exp_homonym = ui.save_jpeg(ui.noise((24, 16), 11), self.exp_root / "otra" / "foto.jpg")
        self.inbox_exif = save_exif_jpeg(self.tmp / "inbox" / "girada.jpg")
        self.inbox_x = ui.save_jpeg(ui.noise((24, 16), 12), self.tmp / "inbox" / "x" / "foto.jpg")
        self.inbox_y = ui.save_jpeg(ui.noise((32, 16), 13), self.tmp / "inbox" / "y" / "foto.jpg")
        self.inbox_other = ui.save_jpeg(ui.noise((16, 16), 14), self.tmp / "inbox" / "otro_cliente.jpg")
        self.inbox_free = ui.save_jpeg(ui.noise((16, 16), 15), self.tmp / "inbox" / "sin_vincular.jpg")
        self.inbox_copy = self.tmp / "inbox" / "copia.jpg"
        self.inbox_copy.write_bytes(self.inbox_jpg.read_bytes())
        link = {"client_id": 7, "expedient_id": 42, "status": "pending"}
        for item_id, path, extra in (
            (10, self.inbox_exif, link),
            (11, self.inbox_x, link),
            (12, self.inbox_y, link),
            (13, self.inbox_other, {"client_id": 8, "expedient_id": 77, "status": "pending"}),
            (14, self.inbox_free, {"status": "pending"}),
            (15, self.inbox_copy, link),
        ):
            self.inbox.items[item_id] = {"id": item_id, "stored_path": str(path),
                                         "original_filename": path.name, **extra}
        self.hashes = {path: ui.sha256(path) for path in self.tmp.rglob("*") if path.is_file()}
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))

    # ------------------------------------------------------------------ helpers

    def item_id(self, path):
        return next(i for i, item in self.inbox.items.items() if item["stored_path"] == str(path))

    def open_compare(self, context, paths, active=0, linking=True):
        if context == "inbox":
            queue = [{"path": str(p), "name": Path(p).name, "key": f"inbox:{self.item_id(p)}",
                      "inbox_item_id": self.item_id(p)} for p in paths]
        else:
            queue = [{"path": str(p), "name": Path(p).name} for p in paths]
        dialog = open_document_viewer_modal(
            self.page, str(paths[active]), title=Path(paths[active]).name,
            expediente_id=None if context == "inbox" else 42, toolbar_actions=self.toolbar(context),
            near_window=0, queue=queue, queue_index=active,
            linking=ViewerLinking() if linking else None)
        self.button(dialog, "Comparador 4").on_click(None)
        return dialog

    def mark(self, dialog, *indexes, value=True):
        for index in indexes:
            viewer_layout(dialog).tiles[index].checkbox.on_change(
                SimpleNamespace(control=SimpleNamespace(value=value)))

    def multi(self, dialog):
        return next((b for b in viewer_action_buttons(dialog) if b.data == MULTI_DATA), None)

    def open_form(self, context, paths, marked=None):
        dialog = self.open_compare(context, paths)
        self.mark(dialog, *(range(len(paths)) if marked is None else marked))
        command = self.multi(dialog)
        self.assertFalse(command.disabled, command.tooltip)
        command.on_click(None)
        form = self.top_form()
        self.assertIsInstance(form, ImagesToPdfForm)
        return dialog, form

    def confirm(self, form):
        form.consent.value = True
        form.consent.on_change(None)

    def converted(self):
        root = self.tools_root / "converted"
        return sorted(root.glob("*.pdf")) if root.exists() else []

    def form_texts(self, form):
        return " ".join(c.value for c in ui.walk(form.dialog.content) if isinstance(c, ft.Text))


class ToolbarTests(ImagesToPdfBase):
    def test_seventh_command_follows_the_comparator_selection(self):
        for context in ("inbox", "expedient"):
            with self.subTest(context=context):
                paths = [self.jpg(context), self.png(context), self.pdf(context)]
                # Single mode keeps the six tools: there is no selection.
                single = self.open_viewer(context, paths[0], queue=paths)
                self.assertEqual([b.data for b in self.image_buttons(single)], ui.IMAGE_DATA)
                self.assertIsNone(self.multi(single))
                self.button(single, "Cerrar").on_click(None)
                # Comparator without linking: no checkboxes, no seventh command.
                plain = self.open_compare(context, paths, linking=False)
                self.assertEqual(len(self.image_buttons(plain)), 6)
                self.button(plain, "Cerrar").on_click(None)

                dialog = self.open_compare(context, paths)
                self.assertEqual([b.data for b in self.image_buttons(dialog)], ui.IMAGE_DATA + [MULTI_DATA])
                command = self.multi(dialog)
                self.assertEqual(viewer_action_label(command), MULTI_LABEL)
                self.assertTrue(command.disabled)
                self.assertEqual(command.tooltip, NO_IMAGE_SELECTION)
                self.mark(dialog, 0)
                self.assertTrue(self.multi(dialog).disabled)
                self.mark(dialog, 1)
                command = self.multi(dialog)
                self.assertFalse(command.disabled, command.tooltip)
                self.assertNotEqual(command.tooltip, adapter.ENABLED_TOOLTIP)
                # A PDF in the selection: refused with the document and the reason.
                self.mark(dialog, 2)
                command = self.multi(dialog)
                self.assertTrue(command.disabled)
                self.assertIn(Path(paths[2]).name, command.tooltip)
                self.assertIn(NOT_IMAGE, command.tooltip)
                # PDF active: its seven commands, no image commands.
                viewer_layout(dialog).tiles[2].container.on_click(None)
                self.assertEqual(viewer_active_document(dialog).path, str(paths[2]))
                self.assertEqual([b.data for b in self.pdf_buttons(dialog)], [op for op, _ in adapter.PDF_ACTIONS])
                self.assertEqual(self.image_buttons(dialog), [])
                self.button(dialog, "Cerrar").on_click(None)
                self.assertEqual(self.page.stack, [])
        self.assertEqual(self.inbox.registered, [])
        self.error.assert_not_called()

    def test_stale_command_after_the_selection_changes_is_inert(self):
        dialog = self.open_compare("expedient", [self.exp_jpg, self.exp_png, self.exp_exif])
        self.mark(dialog, 0, 1)
        stale = self.multi(dialog)
        self.mark(dialog, 1, value=False)
        stale.on_click(None)
        self.assertIsNone(self.top_form())
        self.assertTrue(self.multi(dialog).disabled)
        self.button(dialog, "Cerrar").on_click(None)


class EndToEndTests(ImagesToPdfBase):
    def test_order_pages_alpha_and_exif_in_both_contexts(self):
        for context, exif in (("inbox", self.inbox_exif), ("expedient", self.exp_exif)):
            with self.subTest(context=context):
                self.done.reset_mock()
                before = len(self.inbox.registered)
                # tools_root is shared: the previous context's registered PDF stays.
                existing = self.converted()
                dialog, form = self.open_form(context, [self.jpg(context), self.png(context), exif])
                texts = self.form_texts(form)
                self.assertIn("Destino del registro", texts)
                self.assertIn("orientación EXIF aplicada", texts)
                self.assertIn("con transparencia", texts)
                self.assertEqual([s.source_path for s in form.page_sources()],
                                 [resolved(self.jpg(context)), resolved(self.png(context)), resolved(exif)])
                # Without consent nothing is written.
                self.assertTrue(form.submit_button.disabled)
                form.submit_button.on_click(None)
                self.assertEqual(form.status.color, Q_ERROR)
                self.assertIn(NEED_CONSENT, form.status.value)
                self.assertEqual(self.converted(), existing)
                # Consent, then reorder with the visible arrows: consent is withdrawn.
                self.confirm(form)
                self.assertFalse(form.submit_button.disabled)
                form.order_column.controls[1].controls[1].on_click(None)  # PNG up
                self.assertEqual(form.order, [1, 0, 2])
                self.assertFalse(form.consent.value)
                self.assertTrue(form.submit_button.disabled)
                self.confirm(form)
                form.submit_button.on_click(None)
                self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
                self.assertIn("PDF de 3 página(s)", form.status.value)
                self.assertIn("Originales intactos", form.status.value)
                self.done.assert_called_once()

                outcome = form.outcome
                self.assertEqual(len(outcome["outputs"]), 1)
                output = Path(outcome["outputs"][0])
                self.assertTrue(output.resolve().is_relative_to(self.tools_root.resolve()))
                self.assertEqual(sorted(p.resolve() for p in self.converted()),
                                 sorted(p.resolve() for p in existing + [output]))
                # One page per source, in the confirmed order; EXIF applied (20 x 30).
                self.assertEqual(page_sizes(output), [(40, 20), (64, 48), (20, 30)])
                # The transparent half of the PNG is white, not black.
                self.assertTrue(all(v >= 240 for v in pdf_pixel(output, 0, (5, 10))[:3]))

                self.assertEqual(len(self.inbox.registered), before + 1)
                item = self.inbox.registered[-1]
                self.assertEqual(item["source_type"], "generated")
                self.assertEqual(item["source_label"], "document_tools:images_to_pdf")
                metadata = item["metadata_json"]
                pages = metadata["tool_result"]["metadata"]["pages"]
                self.assertEqual([p["page"] for p in pages], [1, 2, 3])
                self.assertEqual([p["source_path"] for p in pages],
                                 [resolved(self.png(context)), resolved(self.jpg(context)), resolved(exif)])
                self.assertEqual([p["alpha_flattened"] for p in pages], [True, False, False])
                self.assertEqual([p["exif_orientation_applied"] for p in pages], [False, False, True])
                self.assertEqual(metadata["source_paths"], [p["source_path"] for p in pages])
                if context == "inbox":
                    self.assertEqual(metadata["source_item_ids"], [3, 1, 10])
                    self.assertEqual((item["client_id"], item["expedient_id"]), (7, 42))
                else:
                    provenance = metadata["provenance"]
                    self.assertEqual(provenance["source_context"], "expedient")
                    self.assertEqual(provenance["expediente_id"], 42)
                    self.assertEqual([s["source_relative_path"] for s in provenance["sources"]],
                                     ["plano.png", str(Path("fotos/foto.jpg")), "girada.jpg"])
                    self.assertEqual((item["client_id"], item["expedient_id"]), (None, 42))
                form.close()
                self.assertIs(self.page.stack[-1], dialog)
                self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(len(self.inbox.registered), 2)
        self.error.assert_not_called()

    def test_homonyms_are_joined_and_told_apart(self):
        for context, paths in (("inbox", [self.inbox_x, self.inbox_y]),
                               ("expedient", [self.exp_jpg, self.exp_homonym])):
            with self.subTest(context=context):
                dialog, form = self.open_form(context, paths)
                lines = [form._label(index) for index in form.order]
                self.assertEqual(len(set(lines)), 2)
                self.assertTrue(all(line.startswith("foto.jpg") for line in lines))
                self.confirm(form)
                form.submit_button.on_click(None)
                self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
                output = form.outcome["outputs"][0]
                self.assertEqual(len(page_sizes(output)), 2)
                metadata = self.inbox.registered[-1]["metadata_json"]
                if context == "inbox":
                    self.assertEqual(metadata["source_item_ids"], [11, 12])
                else:
                    self.assertEqual([s["source_relative_path"] for s in metadata["provenance"]["sources"]],
                                     [str(Path("fotos/foto.jpg")), str(Path("otra/foto.jpg"))])
                form.close()
                self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(len(self.inbox.registered), 2)

    def test_expedientes_view_offers_the_command(self):
        viewer_dialog = ft.AlertDialog(modal=True)
        self.page.overlay.append(viewer_dialog)
        form_error = Mock()
        scope = ui.bind(ui.EXPEDIENTS, ("show_document_preview",), dict(
            page=self.page, show_form_error=form_error,
            state={"dialog_expediente_id": 42, "viewer_linking": ViewerLinking()},
            open_document_viewer_modal=open_document_viewer_modal, document_viewer_dialog=viewer_dialog,
        ))
        queue = [{"path": str(p), "name": p.name} for p in (self.exp_jpg, self.exp_png)]
        dialog = scope["show_document_preview"](str(self.exp_jpg), queue=queue, queue_index=0)
        self.button(dialog, "Comparador 4").on_click(None)
        self.mark(dialog, 0, 1)
        self.multi(dialog).on_click(None)
        form = self.top_form()
        self.assertIsInstance(form, ImagesToPdfForm)
        self.confirm(form)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        self.assertEqual(self.inbox.registered[0]["metadata_json"]["provenance"]["expediente_id"], 42)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        form_error.assert_not_called()


class RejectionTests(ImagesToPdfBase):
    def test_empty_single_and_duplicate_selections(self):
        for build in (lambda ids: tools.inbox_images_scope(ids),
                      lambda ids: tools.expedient_images_scope(42, [self.exp_jpg][:len(ids)])):
            for ids in ([], [1]):
                with self.assertRaisesRegex(ToolScopeError, "al menos 2"):
                    build(ids)
        with self.assertRaisesRegex(ToolScopeError, "repite"):
            tools.inbox_images_scope([1, 1])
        with self.assertRaisesRegex(ToolScopeError, "duplicada"):
            tools.inbox_images_scope([1, 15])  # same content under another item
        with self.assertRaisesRegex(ToolScopeError, "duplicada"):
            tools.expedient_images_scope(42, [self.exp_jpg, self.exp_root / "fotos" / ".." / "fotos" / "foto.jpg"])

    def test_foreign_invalid_and_mixed_sources(self):
        cases = (
            (lambda: tools.inbox_images_scope([1, 999]), "Bandeja #999"),
            (lambda: tools.inbox_images_scope([1, 6]), "discarded"),
            (lambda: tools.inbox_images_scope([1, 4]), "JPG, JPEG o PNG"),
            (lambda: tools.inbox_images_scope([1, 3], [str(self.inbox_png), str(self.inbox_jpg)]),
             "ya no coincide"),
            (lambda: tools.inbox_images_scope([1, 13]), "misma vinculación"),
            (lambda: tools.inbox_images_scope([1, 14]), "misma vinculación"),
            (lambda: tools.expedient_images_scope(42, [self.exp_jpg, self.inbox_jpg]), "no pertenece"),
            (lambda: tools.expedient_images_scope(42, [self.exp_jpg, self.exp_root / "nada.jpg"]), "no existe"),
            (lambda: tools.expedient_images_scope(42, [self.exp_jpg, self.exp_pdf]), "JPG, JPEG o PNG"),
            (lambda: tools.expedient_images_scope(99, [self.exp_jpg, self.exp_png]), "carpeta"),
        )
        for build, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ToolScopeError, message):
                    build()
        self.assertEqual(self.inbox.registered, [])

    def test_incompatible_links_are_reported_from_the_viewer(self):
        dialog = self.open_compare("inbox", [self.inbox_jpg, self.inbox_other])
        self.mark(dialog, 0, 1)
        self.multi(dialog).on_click(None)
        notice = self.page.stack[-1]
        self.assertIsNot(notice, dialog)
        self.assertIn("misma vinculación", notice.content.value)
        self.error.assert_called_once()
        notice.actions[0].on_click(None)
        self.assertIs(self.page.stack[-1], dialog)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.inbox.registered, [])
        self.assertEqual(self.converted(), [])

    def test_order_must_be_the_reviewed_sources(self):
        scope = tools.expedient_images_scope(42, [self.exp_jpg, self.exp_png])
        for order in ([0], [0, 0], [0, 2], ["x", 1]):
            with self.assertRaisesRegex(ValueError, "orden"):
                tools.run_images_to_pdf(scope, order)
        self.assertFalse(tools.review_spent(scope.token))
        self.assertEqual(self.converted(), [])


class GuardTests(ImagesToPdfBase):
    def test_sources_changed_between_review_and_confirmation(self):
        dialog, form = self.open_form("expedient", [self.exp_jpg, self.exp_png])
        self.exp_png.write_bytes(self.exp_png.read_bytes() + b"\x00editado")
        self.hashes[self.exp_png] = ui.sha256(self.exp_png)
        self.confirm(form)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("ha cambiado", form.status.value)
        self.assertFalse(tools.review_spent(form.scope.token))
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

        dialog, form = self.open_form("inbox", [self.inbox_jpg, self.inbox_png])
        self.inbox.items[3]["status"] = "discarded"
        self.confirm(form)
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("discarded", form.status.value)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.inbox.registered, [])
        self.assertEqual(self.converted(), [])

    def test_double_click_double_submit_and_replay_create_one_copy(self):
        dialog = self.open_compare("inbox", [self.inbox_jpg, self.inbox_png])
        self.mark(dialog, 0, 1)
        command = self.multi(dialog)
        command.on_click(None)
        command.on_click(None)  # the open form is reused
        self.assertEqual(len(self.page.stack), 2)
        form = self.top_form()
        self.confirm(form)
        form.submit_button.on_click(None)
        form.submit_button.on_click(None)
        self.assertEqual(len(self.inbox.registered), 1)
        self.assertEqual(len(self.converted()), 1)
        self.done.assert_called_once()
        self.assertFalse(form.submit_button.visible)
        # Replaying the confirmed review against the service writes nothing.
        with self.assertRaisesRegex(ValueError, "ya se confirmó"):
            tools.run_images_to_pdf(form.scope, form.order)
        self.assertEqual(len(self.inbox.registered), 1)
        self.assertEqual(len(self.converted()), 1)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_write_errors_leave_nothing_and_allow_retry(self):
        dialog, form = self.open_form("inbox", [self.inbox_x, self.inbox_y])
        self.confirm(form)
        failure = DocumentToolResult.failure(operation="images_to_pdf", errors=["Disco lleno."])
        with patch.object(image_tools, "images_to_pdf", return_value=failure):
            form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("Disco lleno", form.status.value)

        def broken_save(img, fp, *args, **kwargs):
            Path(fp).write_bytes(b"%PDF-1.4 parcial")
            raise OSError("Error de escritura simulado")
        with patch.object(Image.Image, "save", broken_save):
            form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_ERROR)
        self.assertIn("Error de escritura simulado", form.status.value)
        self.assertEqual(self.converted(), [])  # the partial PDF was removed
        self.assertEqual(self.inbox.registered, [])
        self.assertFalse(form.submit_button.disabled)

        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        self.assertEqual(len(self.inbox.registered), 1)
        form.close()
        self.button(dialog, "Cerrar").on_click(None)

    def test_registration_error_names_the_unregistered_pdf(self):
        def failing_register(file_path, source_type, source_label, notes, client_id, expedient_id,
                             metadata_json):
            raise OSError("Bandeja bloqueada")

        for context in ("inbox", "expedient"):
            with self.subTest(context=context):
                dialog, form = self.open_form(context, [self.jpg(context), self.png(context)])
                self.confirm(form)
                with patch.object(inbox_tools, "import_file_to_inbox", failing_register):
                    form.submit_button.on_click(None)
                self.assertEqual(form.status.color, Q_ERROR)
                self.assertIn("no se pudo registrar", form.status.value)
                self.assertIn("Bandeja bloqueada", form.status.value)
                output = self.converted()[-1]
                self.assertIn(str(output.resolve()), form.status.value)
                self.assertEqual(len(page_sizes(output)), 2)
                # The written PDF spends the review: no second copy from this form.
                self.assertTrue(tools.review_spent(form.scope.token))
                self.assertTrue(form.submit_button.disabled)
                form.submit_button.on_click(None)
                self.assertIn("ya se confirmó", form.status.value)
                form.close()
                self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(len(self.converted()), 2)
        self.assertEqual(self.inbox.registered, [])
        self.done.assert_not_called()

    def test_single_image_tools_are_unchanged_in_the_comparator(self):
        dialog = self.open_compare("expedient", [self.exp_jpg, self.exp_png])
        self.mark(dialog, 0, 1)
        self.button(dialog, "Rotar").on_click(None)
        form = self.top_form()
        self.assertIsInstance(form, ImageToolForm)
        self.assertNotIsInstance(form, ImagesToPdfForm)
        self.assertEqual(form.scope.source_path, resolved(self.exp_jpg))
        form.submit_button.on_click(None)
        self.assertEqual(form.status.color, Q_SUCCESS, form.status.value)
        self.assertEqual(self.inbox.registered[0]["source_label"], "document_tools:image_rotate")
        form.close()
        self.button(dialog, "Cerrar").on_click(None)


if __name__ == "__main__":
    unittest.main()
