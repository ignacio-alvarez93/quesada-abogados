"""DV30-01: the document viewer takes the whole CRM surface, not a dialog size.

Synthetic PDFs in temporary directories only; no Flet client runs. Pixel
budgets, the semantic modal layout and live window resizes are checked
structurally. The viewer is never the OS full screen.
"""
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from frontend.components import document_viewer_modal as viewer
from frontend.components import document_viewer_multidoc as multidoc
from frontend.components.document_viewer_modal import (
    SUPPORTED_VIEWPORTS, open_document_viewer_modal, viewer_action_buttons,
    viewer_action_label, viewer_layout, viewer_metrics,
)
from frontend.components.document_viewer_notes_panel import ViewerNotes
from frontend.components.pdf_tools_toolbar_adapter import PDF_ACTIONS, PdfToolsToolbarAdapter


# Bounds of the DV23-DV29 dialog that the viewer no longer stops at.
DIALOG_MAX_WIDTH, DIALOG_MAX_HEIGHT = 1600, 980
# Largest safe margin left around the viewer on each side.
MAX_MARGIN = 16


def walk(control):
    yield control
    for name in ("content", "title"):
        child = getattr(control, name, None)
        if isinstance(child, ft.Control):
            yield from walk(child)
    for child in getattr(control, "controls", None) or ():
        yield from walk(child)


class ModernPage:
    """Flet show_dialog stack with a CRM viewport; mounted dialogs patch alone."""

    def __init__(self, size):
        self.width, self.height = size
        self.overlay = []
        self._dialogs = SimpleNamespace(controls=[])
        self.update = Mock()

    def show_dialog(self, dialog):
        dialog.open = True
        self._dialogs.controls.append(dialog)

    def pop_dialog(self):
        dialog = self._dialogs.controls.pop()
        dialog.open = False
        return dialog


class MountedDialog(ft.AlertDialog):
    def update(self):
        self.subtree_updates = getattr(self, "subtree_updates", 0) + 1


def resize_event(width, height):
    return SimpleNamespace(width=width, height=height)


class Dv30FullSurfaceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "sintetico_25.pdf"
        with fitz.open() as document:
            for index in range(25):
                document.new_page(width=595, height=842).insert_text(
                    (72, 72), f"Página sintética {index + 1}", fontsize=24)
            document.save(self.source)
        self.original = self.source.read_bytes()
        # expediente_id=1 resolves to the temporary folder, never the CRM database;
        # otherwise the preview is refused and pages/zoom are rightly disabled.
        root = {"exists": True, "root_path": str(self.root), "message": ""}
        for patcher in (patch.object(service, "PREVIEW_DIR", self.root / "previews"),
                        patch.object(service, "get_expediente_document_root", return_value=root),
                        patch.dict(viewer._TOOLS_PREFERENCE, {"collapsed": False})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.item = {"id": 7, "stored_path": str(self.source)}

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)

    def adapter(self):
        return PdfToolsToolbarAdapter(lambda request: self.item, {"rotate": Mock()}, Mock())

    def notes(self):
        # Loads are never run: the panel's geometry is what is checked here.
        return ViewerNotes(actor={"id": 1, "username": "tester"}, run=lambda work: None)

    def queue(self, count=4):
        return [{"path": str(self.source), "name": f"Doc {n + 1}"} for n in range(count)]

    def open(self, size, **kwargs):
        page = ModernPage(size)
        kwargs.setdefault("dialog", MountedDialog(modal=True))
        return page, open_document_viewer_modal(page, str(self.source), near_window=1, **kwargs)

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def header_close(self, dialog):
        return next(c for c in walk(dialog.title)
                    if isinstance(c, ft.IconButton) and c.icon == ft.Icons.CLOSE)

    def assert_shell_matches(self, dialog, metrics):
        self.assertEqual(dialog.title.width, metrics.outer_width)
        self.assertEqual(dialog.content.width, metrics.content_width)
        self.assertEqual(dialog.actions[0].width, metrics.content_width)
        inset = dialog.inset_padding
        self.assertEqual((inset.left, inset.right, inset.top, inset.bottom),
                         (metrics.inset_h, metrics.inset_h, metrics.inset_v, metrics.inset_v))
        self.assertEqual(dialog.actions[0].content.scroll, ft.ScrollMode.AUTO)
        self.assertIsNotNone(self.header_close(dialog).on_click)
        self.assertIn("Cerrar", [viewer_action_label(b) for b in viewer_action_buttons(dialog)])

    # -- pixel budget ------------------------------------------------------------

    def test_metrics_fill_the_viewport_less_a_safe_margin(self):
        for width, height in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=(width, height)):
                metrics = viewer_metrics(width, height)
                self.assertTrue(0 < metrics.inset_h <= MAX_MARGIN)
                self.assertTrue(0 < metrics.inset_v <= MAX_MARGIN)
                # Whole width and height, nothing beyond them.
                self.assertEqual(metrics.outer_width + 2 * metrics.inset_h, width)
                self.assertEqual(metrics.total_height + 2 * metrics.inset_v, height)
                self.assertLessEqual(metrics.toolbar_width(len(PDF_ACTIONS)), metrics.content_width)
                self.assertGreaterEqual(metrics.canvas_height, 400)
        large = viewer_metrics(1920, 1080)
        self.assertGreater(large.outer_width, DIALOG_MAX_WIDTH)
        self.assertGreater(large.total_height, DIALOG_MAX_HEIGHT)

    def test_metrics_follow_any_window_and_keep_a_given_tier(self):
        for width, height in ((1024, 700), (1280, 720), (2560, 1440), (3440, 1440)):
            with self.subTest(viewport=(width, height)):
                metrics = viewer_metrics(width, height)
                self.assertEqual(metrics.outer_width + 2 * metrics.inset_h, width)
                self.assertEqual(metrics.total_height + 2 * metrics.inset_v, height)
        kept = viewer_metrics(1366, 768, compact=False)
        self.assertFalse(kept.compact)
        self.assertEqual(kept.outer_width + 2 * kept.inset_h, 1366)
        self.assertEqual(kept.total_height + 2 * kept.inset_v, 768)

    def test_static_no_os_full_screen_and_no_dialog_caps(self):
        source = inspect.getsource(viewer)
        self.assertNotIn("full_screen", source)
        metrics_source = inspect.getsource(viewer_metrics)
        self.assertNotIn(str(DIALOG_MAX_WIDTH), metrics_source)
        self.assertNotIn(str(DIALOG_MAX_HEIGHT), metrics_source)
        for forbidden in ("sqlite3", "boxsdk", "box_service"):
            self.assertNotIn(forbidden, source)

    def test_window_only_viewport_never_touches_full_screen(self):
        window = SimpleNamespace(width=1600, height=900, full_screen=False)
        page = SimpleNamespace(overlay=[], update=Mock(), window=window)
        dialog = open_document_viewer_modal(page, str(self.source), near_window=1)
        self.assertEqual(viewer_layout(dialog).metrics.viewport, (1600, 900))
        self.assertFalse(window.full_screen)
        self.assertEqual((window.width, window.height), (1600, 900))
        self.button(dialog, "Cerrar").on_click(None)

    # -- semantic layout at the supported resolutions ------------------------------

    def test_full_viewer_at_each_resolution_with_notes_queue_and_tools(self):
        for size in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=size):
                _, dialog = self.open(size, toolbar_actions=self.adapter(), queue=self.queue(),
                                      notes=self.notes(), expediente_id=1)
                layout = viewer_layout(dialog)
                metrics = layout.metrics
                self.assertEqual(metrics.viewport, size)
                self.assert_shell_matches(dialog, metrics)
                strip = multidoc.strip_height(metrics) + 10
                self.assertEqual(layout.canvas.height, metrics.canvas_height - strip)
                # Notes panel beside the canvas, as tall as it and unfolded.
                panel = layout.notes.container
                self.assertEqual(panel.data, "notes-panel")
                self.assertFalse(layout.notes.collapsed)
                self.assertEqual(panel.height, layout.canvas.height)
                self.assertIn(panel, list(walk(dialog.content)))
                self.assertGreaterEqual(metrics.content_width - layout.notes.space, 900)
                self.button(dialog, "Cerrar").on_click(None)
                self.assertFalse(dialog.open)
                self.assertIsNone(dialog.content)

    def test_comparator_mosaic_uses_the_full_canvas(self):
        for size in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=size):
                _, dialog = self.open(size, queue=self.queue(), notes=self.notes(),
                                      expediente_id=1)
                self.button(dialog, "Comparador 4").on_click(None)
                layout = viewer_layout(dialog)
                metrics = layout.metrics
                self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
                self.assertEqual(len(layout.tiles), 4)
                self.assert_shell_matches(dialog, metrics)
                width = metrics.content_width - layout.notes.space
                for tile in layout.tiles:
                    self.assertEqual(tile.container.width, (width - 10) // 2)
                    self.assertEqual(tile.container.height, (layout.canvas.height - 10) // 2)
                self.header_close(dialog).on_click(None)
                self.assertFalse(dialog.open)

    # -- live resize -------------------------------------------------------------

    def test_resize_relayouts_single_mode_without_render_or_page_update(self):
        page, dialog = self.open((1366, 768), initial_page=4, toolbar_actions=self.adapter(),
                                 notes=self.notes(), expediente_id=1)
        self.button(dialog, "Zoom +").on_click(None)
        layout = viewer_layout(dialog)
        canvas, list_view = layout.canvas, layout.canvas.content
        spacer = list_view.controls[0].height
        updates, subtree = page.update.call_count, dialog.subtree_updates
        with patch.object(service, "create_document_preview") as render:
            page.on_resize(resize_event(1920, 1080))
            render.assert_not_called()
        metrics = layout.metrics
        self.assertIs(viewer_layout(dialog), layout)
        self.assertEqual(metrics.viewport, (1920, 1080))
        self.assertTrue(metrics.compact)  # the opening tier stays
        self.assert_shell_matches(dialog, metrics)
        self.assertEqual(canvas.height, metrics.canvas_height)
        self.assertEqual(layout.notes.container.height, canvas.height)
        # Same ListView and slot extents: page, zoom and scroll offset stay.
        self.assertIs(canvas.content, list_view)
        self.assertEqual(list_view.controls[0].height, spacer)
        self.assertEqual(layout.page_label.value, "Página 4 de 25")
        self.assertEqual(layout.zoom_label.value, "Zoom: 2.0x")
        self.assertEqual(page.update.call_count, updates)
        self.assertEqual(dialog.subtree_updates, subtree + 1)
        # Same size again: nothing to do.
        page.on_resize(resize_event(1920, 1080))
        self.assertEqual(dialog.subtree_updates, subtree + 1)
        # Navigation after a resize builds at the new size.
        self.button(dialog, "Siguiente").on_click(None)
        self.assertEqual(viewer_layout(dialog).page_label.value, "Página 5 de 25")
        self.assertEqual(dialog.content.width, metrics.content_width)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertFalse(dialog.open)

    def test_shrinking_below_the_toolbar_scrolls_it_and_keeps_close(self):
        page, dialog = self.open((1920, 1080), toolbar_actions=self.adapter())
        page.on_resize(resize_event(1100, 700))
        metrics = viewer_layout(dialog).metrics
        self.assertFalse(metrics.compact)
        self.assertEqual(metrics.outer_width + 2 * metrics.inset_h, 1100)
        self.assertEqual(metrics.total_height + 2 * metrics.inset_v, 700)
        self.assertGreater(metrics.toolbar_width(len(PDF_ACTIONS)), metrics.content_width)
        self.assert_shell_matches(dialog, metrics)
        self.header_close(dialog).on_click(None)
        self.assertFalse(dialog.open)

    def test_resize_keeps_comparator_group_page_and_selection(self):
        page, dialog = self.open((1600, 900), queue=self.queue(), notes=self.notes(),
                                 expediente_id=1)
        self.button(dialog, "Comparador 4").on_click(None)
        self.button(dialog, "Siguiente").on_click(None)
        comparator = viewer_layout(dialog).comparator
        self.assertEqual(comparator.tile_for(0).page, 2)
        with patch.object(service, "create_document_preview") as render:
            page.on_resize(resize_event(1366, 768))
            render.assert_not_called()
        layout = viewer_layout(dialog)
        metrics = layout.metrics
        self.assertEqual(metrics.viewport, (1366, 768))
        self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
        self.assertEqual(comparator.tile_for(0).page, 2)
        self.assertEqual(layout.document.index, 0)
        self.assert_shell_matches(dialog, metrics)
        width = metrics.content_width - layout.notes.space
        self.assertTrue(all(t.container.width == (width - 10) // 2 for t in layout.tiles))
        self.button(dialog, "Documento único").on_click(None)
        self.assertEqual(viewer_layout(dialog).page_label.value, "Página 2 de 25")
        self.assertEqual(dialog.content.width, metrics.content_width)
        self.button(dialog, "Cerrar").on_click(None)

    # -- the CRM's own resize handler -------------------------------------------

    def test_crm_resize_handler_is_chained_and_restored_on_close(self):
        crm = Mock()
        page = ModernPage((1366, 768))
        page.on_resize = crm
        dialog = open_document_viewer_modal(page, str(self.source), near_window=1,
                                            dialog=MountedDialog(modal=True))
        handler = page.on_resize
        event = resize_event(1600, 900)
        handler(event)
        crm.assert_called_once_with(event)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertIs(page.on_resize, crm)
        # A late event on the closed viewer is inert; the CRM still gets it.
        updates = page.update.call_count
        handler(resize_event(1920, 1080))
        self.assertIsNone(dialog.content)
        self.assertEqual(page.update.call_count, updates)
        self.assertEqual(crm.call_count, 2)

    def test_dismiss_restores_handler_and_reuse_does_not_chain(self):
        crm = Mock()
        page = ModernPage((1366, 768))
        page.on_resize = crm
        dialog = MountedDialog(modal=True)
        open_document_viewer_modal(page, str(self.source), near_window=1, dialog=dialog)
        open_document_viewer_modal(page, str(self.source), near_window=1, dialog=dialog)
        self.assertIs(page.on_resize._viewer_previous, crm)
        page.on_resize(resize_event(1920, 1080))
        crm.assert_called_once()
        self.assertEqual(viewer_layout(dialog).metrics.viewport, (1920, 1080))
        dialog.on_dismiss(None)
        self.assertIs(page.on_resize, crm)
        self.assertIsNone(dialog.content)


if __name__ == "__main__":
    unittest.main()
