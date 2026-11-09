"""DV23 visual structure of the document viewer, with synthetic PDFs only.

No Flet client runs here: hierarchy, grouping and pixel budgets are checked
structurally against the approved mockup (docs/mockups, never imported).
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from frontend.components import document_viewer_modal as viewer
from frontend.components.document_viewer_modal import (
    SUPPORTED_VIEWPORTS, open_document_viewer_modal, viewer_action_buttons,
    viewer_action_label, viewer_layout, viewer_metrics,
)
from frontend.components.pdf_tools_toolbar_adapter import PDF_ACTIONS, PdfToolsToolbarAdapter


TOOL_LABELS = [label for _, label in PDF_ACTIONS]


def walk(control):
    yield control
    for name in ("content", "title"):
        child = getattr(control, name, None)
        if isinstance(child, ft.Control):
            yield from walk(child)
    for child in getattr(control, "controls", None) or ():
        yield from walk(child)


def texts(control):
    return [c.value for c in walk(control) if isinstance(c, ft.Text)]


def row_width(row):
    """Fixed width of the toolbar row, as laid out without stretching."""
    total = 0
    for child in row.controls:
        if isinstance(child, ft.Column):  # a command group
            commands = child.controls[1]
            widths = [c.width for c in commands.controls]
            assert all(isinstance(w, (int, float)) for w in widths), widths
            total += sum(widths) + commands.spacing * (len(widths) - 1)
        else:
            margin = child.margin.left + child.margin.right if child.margin else 0
            total += child.width + margin
    return total


class Dv23VisualTests(unittest.TestCase):
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
        patcher = patch.object(service, "PREVIEW_DIR", self.root / "previews")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.item = {"id": 7, "stored_path": str(self.source)}
        self.handlers = {"rotate": Mock(), "split": Mock()}

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)

    def page(self, size=None):
        page = SimpleNamespace(overlay=[], update=Mock())
        if size:
            page.width, page.height = size
        return page

    def adapter(self):
        return PdfToolsToolbarAdapter(lambda request: self.item, self.handlers, Mock())

    def open(self, size=None, **kwargs):
        page = self.page(size)
        return page, open_document_viewer_modal(page, str(self.source), near_window=1, **kwargs)

    def toolbar_row(self, dialog):
        (toolbar,) = dialog.actions
        return toolbar.content

    def test_pixel_budget_fits_every_supported_resolution(self):
        for width, height in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=(width, height)):
                metrics = viewer_metrics(width, height)
                self.assertLessEqual(metrics.outer_width + 2 * metrics.inset_h, width)
                self.assertLessEqual(metrics.total_height + 2 * metrics.inset_v, height)
                self.assertLessEqual(metrics.toolbar_width(len(PDF_ACTIONS)), metrics.content_width)
                self.assertGreaterEqual(metrics.canvas_height, 400)
        self.assertTrue(viewer_metrics(1366, 768).compact)
        self.assertFalse(viewer_metrics(1920, 1080).compact)

    def test_built_toolbar_fits_without_clipping_at_each_resolution(self):
        queue = [{"path": str(self.source), "name": "A"}, {"path": str(self.source), "name": "B"}]
        for size in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=size):
                page, dialog = self.open(size, toolbar_actions=self.adapter(), queue=queue)
                metrics = viewer_layout(dialog).metrics
                self.assertEqual(metrics.viewport, size)
                row = self.toolbar_row(dialog)
                # Inner width: content width minus padding (2 x 12) and border (2 x 1).
                self.assertEqual(row_width(row), metrics.content_width - 26)
                self.assertEqual(row.scroll, ft.ScrollMode.AUTO)  # never clipped if smaller
                self.assertEqual(dialog.actions[0].width, metrics.content_width)
                self.assertEqual(dialog.title.width, metrics.outer_width)
                self.assertEqual(dialog.content.width, metrics.content_width)
                self.button(dialog, "Cerrar").on_click(None)

    def test_unknown_window_size_uses_smallest_supported_layout(self):
        _, dialog = self.open()
        self.assertEqual(viewer_layout(dialog).metrics.viewport, (1366, 768))

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def test_header_info_row_canvas_and_grouped_toolbar_hierarchy(self):
        _, dialog = self.open((1600, 900), initial_page=4, toolbar_actions=self.adapter())
        layout = viewer_layout(dialog)
        header = texts(dialog.title)
        self.assertEqual(header[:2], ["Visor documental", "sintetico_25.pdf"])
        self.assertIn("Quesada Abogados", header)
        self.assertIsInstance(dialog.title.gradient, ft.LinearGradient)
        self.assertTrue(any(isinstance(c, ft.IconButton) and c.icon == ft.Icons.CLOSE
                            for c in walk(dialog.title)))
        # Info row: truncable path, page and zoom indicators.
        self.assertEqual(layout.path.value, str(self.source))
        self.assertEqual(layout.path.overflow, ft.TextOverflow.ELLIPSIS)
        self.assertEqual(layout.path.max_lines, 1)
        self.assertEqual(layout.page_label.value, "Página 4 de 25")
        self.assertEqual(layout.zoom_label.value, "Zoom: 1.6x")
        info_row, canvas = dialog.content.content.controls
        self.assertIs(canvas, layout.canvas)
        self.assertIn(layout.page_label, list(walk(info_row)))
        self.assertIsInstance(canvas.content, ft.ListView)
        self.assertEqual(canvas.height, layout.metrics.canvas_height)
        # Toolbar groups in the approved order; exit group at the right edge.
        groups = [c for c in self.toolbar_row(dialog).controls if isinstance(c, ft.Column)]
        titles = [texts(g.controls[0]) for g in groups]
        self.assertEqual(titles, [["EDICIÓN Y PROCESAMIENTO DEL PDF"], ["NAVEGACIÓN"], ["ZOOM"], []])
        labels = [[viewer_action_label(b) for b in g.controls[1].controls] for g in groups]
        self.assertEqual(labels, [TOOL_LABELS, ["Anterior", "Siguiente"], ["Zoom -", "Zoom +"],
                                  ["Abrir con visor del sistema", "Cerrar"]])
        self.assertEqual([viewer_action_label(b) for b in viewer_action_buttons(dialog)],
                         sum(labels, []))

    def test_tool_tiles_keep_adapter_state_and_show_icon_over_label(self):
        _, dialog = self.open((1366, 768), toolbar_actions=self.adapter())
        metrics = viewer_layout(dialog).metrics
        tiles = viewer_action_buttons(dialog)[:len(PDF_ACTIONS)]
        for tile, (operation, label) in zip(tiles, PDF_ACTIONS):
            icon, text = tile.content.controls
            self.assertIsInstance(icon, ft.Icon)
            self.assertEqual(icon.icon, viewer._TOOL_ICONS[operation])
            self.assertEqual(text.value, label)
            self.assertEqual((tile.width, tile.height), (metrics.tile_width, metrics.tile_height))
            self.assertEqual(tile.data, operation)
            # P1 relocates the tools; it never disables an available workflow.
            self.assertEqual(tile.disabled, operation not in self.handlers)
            self.assertEqual(tile.on_click is None, operation not in self.handlers)
        self.button(dialog, "Rotar páginas").on_click("evt")
        self.handlers["rotate"].assert_called_once_with("evt", item_id=7)

    def test_without_toolbar_factory_there_is_no_edit_group(self):
        _, dialog = self.open((1920, 1080))
        groups = [c for c in self.toolbar_row(dialog).controls if isinstance(c, ft.Column)]
        self.assertEqual([texts(g.controls[0]) for g in groups], [["NAVEGACIÓN"], ["ZOOM"], []])

    def test_disabled_commands_explain_their_real_reason(self):
        _, dialog = self.open(initial_page=1, initial_zoom=0.8)
        previous, zoom_out = self.button(dialog, "Anterior"), self.button(dialog, "Zoom -")
        self.assertTrue(previous.disabled and zoom_out.disabled)
        self.assertEqual(previous.tooltip, "Ya estás en la primera página.")
        self.assertEqual(zoom_out.tooltip, "Zoom mínimo alcanzado.")
        enabled = [self.button(dialog, label) for label in
                   ("Siguiente", "Zoom +", "Abrir con visor del sistema", "Cerrar")]
        self.assertTrue(all(not b.disabled and callable(b.on_click) for b in enabled))
        self.button(dialog, "Cerrar").on_click(None)

    def test_missing_document_disables_zoom_with_reason(self):
        page = self.page()
        dialog = open_document_viewer_modal(page, str(self.root / "missing.pdf"))
        zoom_in = self.button(dialog, "Zoom +")
        self.assertTrue(zoom_in.disabled)
        self.assertEqual(zoom_in.tooltip, "No hay vista previa para ampliar.")
        self.assertEqual(viewer_layout(dialog).zoom_label.value, "Zoom: —")
        self.assertEqual(dialog.content.content.controls[-1].content.value, "El documento no existe.")

    def test_navigation_updates_info_row_in_place(self):
        _, dialog = self.open(initial_page=4)
        self.button(dialog, "Siguiente").on_click(None)
        self.assertEqual(viewer_layout(dialog).page_label.value, "Página 5 de 25")
        self.button(dialog, "Zoom +").on_click(None)
        self.assertEqual(viewer_layout(dialog).zoom_label.value, "Zoom: 2.0x")
        self.assertEqual(viewer_layout(dialog).page_label.value, "Página 5 de 25")

    def test_header_close_button_closes_like_toolbar_close(self):
        page, dialog = self.open()
        close = next(c for c in walk(dialog.title) if isinstance(c, ft.IconButton))
        close.on_click(None)
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.content)
        self.assertEqual(page.overlay, [])

    def test_mockup_is_a_reference_only(self):
        source = Path(viewer.__file__).read_text(encoding="utf-8")
        self.assertNotIn("mockups", source)
        self.assertNotIn(".png\"", source)


if __name__ == "__main__":
    unittest.main()
