"""Expedientes and Bandeja viewer integrations (WO-DV22B) with synthetic PDFs and fakes only."""
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from frontend.components.app_button import secondary_button
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label, viewer_layout,
)
from frontend.components.pdf_tools_toolbar_adapter import PdfToolsToolbarAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPEDIENTS = REPO_ROOT / "frontend" / "views" / "expedients_view.py"
INBOX = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"
EXPEDIENT_FUNCTIONS = ("close_document_list_dialog", "open_document_with_system",
                       "show_document_preview", "show_expediente_documents_dialog")
INBOX_FUNCTIONS = ("selected_item", "pdf_toolbar_for_item", "inbox_viewer_options",
                   "show_preview", "detail_show_preview", "show_batch_item_preview")


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def view_functions(path, names):
    found = {}
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            found.setdefault(node.name, []).append(node)
    assert all(len(found.get(name, ())) == 1 for name in names), sorted(found)
    return [found[name][0] for name in names]


def bind(path, names, scope):
    """Execute view closures at module level; free names resolve from scope."""
    module = ast.Module(body=view_functions(path, names), type_ignores=[])
    exec(compile(module, f"<{path.name}>", "exec"), scope)
    return scope


class ModernPage:
    """Flet show_dialog/pop_dialog stack, as in the runtime scroll suite."""

    def __init__(self):
        self.overlay = []
        self._dialogs = SimpleNamespace(controls=[])
        self.update = Mock()
        self.popped = 0

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
        self.popped += 1
        dialog = self._dialogs.controls[-1]
        dialog.open = False
        return dialog


class ViewerIntegrationBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.first = self.root / "first.pdf"
        self.second = self.root / "second.pdf"
        for path in (self.first, self.second):
            with fitz.open() as document:
                for index in range(8):
                    document.new_page(width=150, height=150).insert_text((20, 30), f"{path.stem} {index + 1}")
                document.save(path)
        self.originals = {path: path.read_bytes() for path in (self.first, self.second)}
        for target, value in (("PREVIEW_DIR", self.root / "previews"),
                              ("get_expediente_document_root",
                               Mock(return_value={"exists": True, "root_path": str(self.root)}))):
            patcher = patch.object(service, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.page = SimpleNamespace(overlay=[], update=Mock())

    def tearDown(self):
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content, path)

    def button(self, dialog, label):
        return next(action for action in viewer_action_buttons(dialog) if viewer_action_label(action) == label)

    def texts(self, dialog):
        # DV23: name in the header, path and page in the info row.
        layout = viewer_layout(dialog)
        return [layout.title.value, layout.path.value, layout.page_label.value]

    def status(self, dialog):
        layout = viewer_layout(dialog)
        return [layout.page_label.value, layout.queue_label.value, layout.zoom_label.value]

    def list_view(self, dialog):
        return dialog.content.content.controls[-1].content


class ExpedientViewerIntegrationTests(ViewerIntegrationBase):
    def bind_expedients(self, canonical=open_document_viewer_modal):
        self.state = {"dialog_expediente_id": 42}
        self.form_error = Mock()
        self.cards = []
        self.list_dialog = ft.AlertDialog(modal=True)
        self.viewer_dialog = ft.AlertDialog(modal=True)
        self.page.overlay.extend([self.list_dialog, self.viewer_dialog])
        self.documents = SimpleNamespace(open_document=Mock(), list_expediente_documents=Mock(return_value={
            "root_path": str(self.root),
            "total_documents": 2,
            "documents": [{"path": str(path), "name": path.name, "previewable": True, "type": "pdf"}
                          for path in (self.first, self.second)],
        }))

        def card(**kwargs):
            self.cards.append(kwargs)
            return ft.Container()

        return bind(EXPEDIENTS, EXPEDIENT_FUNCTIONS, dict(
            ft=ft, page=self.page, state=self.state, show_form_error=self.form_error,
            document_viewer_service=self.documents, document_file_card=card,
            secondary_button=secondary_button, Q_PRIMARY_DARK="#003B7A", Q_MUTED="#64748B",
            document_list_dialog=self.list_dialog, document_viewer_dialog=self.viewer_dialog,
            open_document_viewer_modal=canonical,
        ))

    def open_listing(self, scope):
        scope["show_expediente_documents_dialog"]()
        self.assertTrue(self.list_dialog.open)
        return self.list_dialog.title, self.list_dialog.content, list(self.list_dialog.actions)

    def test_list_and_viewer_are_separate_overlay_dialogs(self):
        source = EXPEDIENTS.read_text(encoding="utf-8")
        list_append = "page.overlay.append(document_list_dialog)"
        viewer_append = "page.overlay.append(document_viewer_dialog)"
        self.assertEqual((source.count(list_append), source.count(viewer_append)), (1, 1))
        # The viewer is registered after the listing, so it renders on top of it.
        self.assertLess(source.index(list_append), source.index(viewer_append))
        listing, preview, close = view_functions(EXPEDIENTS, (
            "show_expediente_documents_dialog", "show_document_preview", "close_document_list_dialog"))
        self.assertNotIn("document_viewer_dialog", ast.unparse(listing))
        self.assertNotIn("document_viewer_dialog", ast.unparse(close))
        self.assertIn("dialog=document_viewer_dialog", ast.unparse(preview))

    def test_closing_preview_keeps_listing_open_and_untouched(self):
        scope = self.bind_expedients()
        title, content, actions = self.open_listing(scope)
        self.cards[0]["on_preview"](None)
        self.assertTrue(self.viewer_dialog.open)
        self.assertEqual(self.texts(self.viewer_dialog)[:3], ["first.pdf", str(self.first), "Página 1 de 8"])
        self.assertIs(self.list_dialog.content, content)
        self.assertIs(self.list_dialog.title, title)
        self.assertEqual(len(self.list_dialog.actions), len(actions))
        self.assertTrue(all(a is b for a, b in zip(self.list_dialog.actions, actions)))
        self.assertIsNone(self.list_dialog.data)
        self.button(self.viewer_dialog, "Cerrar").on_click(None)
        self.assertFalse(self.viewer_dialog.open)
        self.assertTrue(self.list_dialog.open)
        self.assertIs(self.list_dialog.content, content)
        # The listing stays operational and closes only itself.
        self.cards[1]["on_preview"](None)
        self.assertTrue(self.viewer_dialog.open)
        self.button(self.viewer_dialog, "Cerrar").on_click(None)
        self.list_dialog.actions[0].on_click(None)
        self.assertFalse(self.list_dialog.open)
        self.assertEqual(len(self.page.overlay), 2)
        self.form_error.assert_not_called()

    def test_dismiss_and_reopen_leave_no_ghost_overlay_or_stale_commands(self):
        scope = self.bind_expedients()
        self.open_listing(scope)
        self.cards[0]["on_preview"](None)
        stale_next = self.button(self.viewer_dialog, "Siguiente")
        stale_close = self.button(self.viewer_dialog, "Cerrar")
        self.viewer_dialog.on_dismiss(None)
        self.assertFalse(self.viewer_dialog.open)
        self.cards[1]["on_preview"](None)
        self.assertTrue(self.viewer_dialog.open)
        reopened = self.viewer_dialog.content
        with patch.object(service, "create_document_preview") as render:
            stale_next.on_click(None)
            stale_close.on_click(None)
            render.assert_not_called()
        self.assertTrue(self.viewer_dialog.open)
        self.assertIs(self.viewer_dialog.content, reopened)
        self.assertEqual(self.texts(self.viewer_dialog)[0], "second.pdf")
        self.button(self.viewer_dialog, "Cerrar").on_click(None)
        self.viewer_dialog.on_dismiss(None)
        self.assertEqual(len(self.page.overlay), 2)
        self.assertIs(self.page.overlay[0], self.list_dialog)
        self.assertIs(self.page.overlay[1], self.viewer_dialog)
        self.assertTrue(self.list_dialog.open)

    def test_cards_keep_the_listing_expediente_context(self):
        canonical = Mock()
        scope = self.bind_expedients(canonical)
        self.open_listing(scope)
        self.documents.list_expediente_documents.assert_called_once_with(42)
        self.state["dialog_expediente_id"] = 99
        self.cards[1]["on_preview"](None)
        canonical.assert_called_once_with(
            self.page, str(self.second), title="second.pdf", expediente_id=42,
            initial_page=1, initial_zoom=1.6, queue=None, queue_index=0,
            dialog=self.viewer_dialog, on_error=self.form_error,
        )
        self.cards[1]["on_open"](None)
        self.documents.open_document.assert_called_once_with(str(self.second), expediente_id=42)
        self.state.clear()
        scope["show_document_preview"](str(self.first))
        self.form_error.assert_called_once()
        self.assertEqual(canonical.call_count, 1)


class InboxViewerIntegrationTests(ViewerIntegrationBase):
    def bind_inbox(self, page=None, canonical=open_document_viewer_modal):
        self.items = {
            1: {"id": 1, "stored_path": str(self.first), "original_filename": "Primero.pdf"},
            2: {"id": 2, "stored_path": str(self.second), "original_filename": "Segundo.pdf"},
        }
        self.state = {"selected_item_id": 1, "selected_item_ids": {1}}
        self.tools = {name: Mock() for name in ("rotate", "move_page", "split", "compress")}
        self.inbox_error = Mock()
        self.batch_message = SimpleNamespace(content=None, update=Mock())
        return bind(INBOX, INBOX_FUNCTIONS, dict(
            page=page or self.page, state=self.state, open_document_viewer_modal=canonical,
            PdfToolsToolbarAdapter=PdfToolsToolbarAdapter,
            document_inbox_service=SimpleNamespace(get_inbox_item=lambda item_id: self.items.get(int(item_id))),
            open_document_tool_rotate_dialog=self.tools["rotate"],
            open_document_tool_reorder_dialog=self.tools["move_page"],
            open_document_tool_split_dialog=self.tools["split"],
            run_document_tool_compress_pdf=self.tools["compress"],
            show_error=self.inbox_error, batch_detail_message=self.batch_message,
            error_alert=lambda text: ft.Text(str(text)),
            item=self.items[2],  # detail_show_preview closes over its dialog item
        ))

    def test_three_paths_share_one_helper_for_the_same_item(self):
        calls = [n for n in ast.walk(parse(INBOX)) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "open_document_viewer_modal"]
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual([ast.unparse(arg) for arg in call.args], ["page"])
            self.assertEqual(len(call.keywords), 1)
            self.assertIsNone(call.keywords[0].arg)
            self.assertEqual(ast.unparse(call.keywords[0].value.func), "inbox_viewer_options")
        canonical = Mock()
        scope = self.bind_inbox(canonical=canonical)
        self.state["selected_item_id"] = 2
        scope["show_preview"]()
        scope["detail_show_preview"]()
        scope["show_batch_item_preview"](self.items[2])
        self.assertEqual(canonical.call_count, 3)
        for call in canonical.call_args_list:
            self.assertEqual(call.args, (self.page,))
            self.assertEqual(call.kwargs["file_path"], str(self.second))
            self.assertEqual(call.kwargs["title"], "Segundo.pdf")
            self.assertEqual((call.kwargs["expediente_id"], call.kwargs["initial_page"],
                              call.kwargs["initial_zoom"]), (None, 1, 1.6))
            self.assertIsInstance(call.kwargs["toolbar_actions"], PdfToolsToolbarAdapter)
        self.inbox_error.assert_not_called()

    def test_preview_and_toolbar_keep_item_identity_after_selection_changes(self):
        scope = self.bind_inbox()
        scope["show_preview"]()
        dialog = self.page.overlay[-1]
        self.state["selected_item_id"] = 2
        self.assertEqual(self.texts(dialog)[:2], ["Primero.pdf", str(self.first)])
        rotate = self.button(dialog, "Rotar páginas")
        self.assertFalse(rotate.disabled)
        rotate.on_click(None)
        self.tools["rotate"].assert_called_once_with(None, item_id=1)
        self.button(dialog, "Siguiente").on_click(None)
        self.button(dialog, "Comprimir PDF").on_click(None)
        self.tools["compress"].assert_called_once_with(None, item_id=1)
        # A re-registered item for that path disables stale commands with a visible error.
        current = self.button(dialog, "Dividir PDF")
        self.items[1] = dict(self.items[1], stored_path=str(self.second))
        current.on_click(None)
        self.tools["split"].assert_not_called()
        self.assertIn("ya no coincide", str(self.inbox_error.call_args.args[0]))
        self.assertEqual(self.state["selected_item_id"], 2)

    def test_detail_preview_closes_only_the_viewer_dialog(self):
        page = ModernPage()
        scope = self.bind_inbox(page=page)
        detail = ft.AlertDialog(modal=True)
        page.show_dialog(detail)
        scope["detail_show_preview"]()
        viewer = page._dialogs.controls[-1]
        self.assertIsNot(viewer, detail)
        self.assertEqual(self.texts(viewer)[:2], ["Segundo.pdf", str(self.second)])
        self.button(viewer, "Cerrar").on_click(None)
        viewer.on_dismiss(SimpleNamespace(control=viewer))
        self.assertEqual(page.popped, 1)
        self.assertEqual(len(page._dialogs.controls), 1)
        self.assertIs(page._dialogs.controls[0], detail)
        self.assertTrue(detail.open)
        self.assertFalse(viewer.open)
        self.assertEqual(page.overlay, [])
        self.assertEqual(self.state, {"selected_item_id": 1, "selected_item_ids": {1}})
        self.inbox_error.assert_not_called()

    def test_batch_path_uses_linked_document_and_reports_missing_path(self):
        scope = self.bind_inbox()
        linked = {"id": 3, "stored_path": "", "linked_document_path": str(self.first),
                  "stored_filename": "grupo.pdf"}
        scope["show_batch_item_preview"](linked)
        dialog = self.page.overlay[-1]
        self.assertEqual(self.texts(dialog)[:2], ["grupo.pdf", str(self.first)])
        # Unregistered copy: PDF commands stay visible but disabled.
        self.assertTrue(self.button(dialog, "Rotar páginas").disabled)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.page.overlay, [])
        scope["show_batch_item_preview"]({"id": 4, "original_filename": "vacío.pdf"})
        self.assertEqual(self.batch_message.content.value, "El documento no tiene ruta interna disponible.")
        self.batch_message.update.assert_called_once()
        self.assertEqual(self.page.overlay, [])
        self.inbox_error.assert_not_called()

    def test_empty_or_missing_path_shows_controlled_error_without_changing_selection(self):
        scope = self.bind_inbox()
        self.items[1]["stored_path"] = None
        scope["show_preview"]()
        self.assertEqual(str(self.inbox_error.call_args.args[0]), "El documento no tiene ruta interna disponible.")
        self.assertEqual(self.page.overlay, [])
        self.items[2]["stored_path"] = "   "
        scope["detail_show_preview"]()
        self.assertEqual(self.inbox_error.call_count, 2)
        self.assertEqual(self.page.overlay, [])
        # A registered path that vanished renders a visible message inside the viewer.
        self.items[1]["stored_path"] = str(self.root / "missing.pdf")
        scope["show_preview"]()
        dialog = self.page.overlay[-1]
        self.assertTrue(dialog.open)
        self.assertNotIn("Rotar páginas", [viewer_action_label(a) for a in viewer_action_buttons(dialog)])
        self.assertEqual(self.texts(dialog)[1], str(self.root / "missing.pdf"))
        self.assertEqual(dialog.content.content.controls[-1].content.value, "El documento no existe.")
        self.assertEqual(self.state, {"selected_item_id": 1, "selected_item_ids": {1}})


class ViewerUxRegressionTests(ViewerIntegrationBase):
    def test_status_line_tracks_queue_and_zoom_with_deep_scroll(self):
        queue = [{"path": str(self.first), "name": "Uno"}, {"path": str(self.second), "name": "Dos"}]
        dialog = open_document_viewer_modal(self.page, str(self.first), title="Uno", queue=queue)
        self.assertEqual(self.status(dialog), ["Página 1 de 8", "Documento 1 de 2", "Zoom: 1.6x"])
        self.assertIsInstance(self.list_view(dialog), ft.ListView)
        self.list_view(dialog).on_scroll(SimpleNamespace(pixels=6 * 1648))
        self.assertEqual(self.status(dialog), ["Página 7 de 8", "Documento 1 de 2", "Zoom: 1.6x"])
        self.assertEqual(dialog.data.current_request.page_number, 7)
        self.button(dialog, "Zoom +").on_click(None)
        self.assertEqual(self.status(dialog), ["Página 7 de 8", "Documento 1 de 2", "Zoom: 2.0x"])
        self.list_view(dialog).on_scroll(SimpleNamespace(pixels=7 * 2048))
        self.assertEqual(dialog.data.current_request.page_number, 8)
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(self.texts(dialog), ["Dos", str(self.second), "Página 1 de 8"])
        self.assertEqual(self.status(dialog), ["Página 1 de 8", "Documento 2 de 2", "Zoom: 2.0x"])
        self.assertTrue(self.button(dialog, "Doc siguiente").disabled)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertFalse(dialog.open)
        self.assertEqual(self.page.overlay, [])

    def test_single_image_shows_zoom_in_info_row_without_queue_status(self):
        # DV23 moves the inline zoom label of the canvas to the fixed info row.
        image = self.root / "image.png"
        fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5, 5), False).save(image)
        dialog = open_document_viewer_modal(self.page, str(image))
        layout = viewer_layout(dialog)
        self.assertEqual(self.status(dialog), ["Página 1 de 1", "", "Zoom: 1.6x"])
        self.assertFalse(layout.queue_label.visible)
        self.assertEqual(len(self.list_view(dialog).controls), 1)


if __name__ == "__main__":
    unittest.main()
