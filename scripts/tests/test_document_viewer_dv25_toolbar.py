"""WO-DV25-P2: foldable "Herramientas PDF" band of the document viewer.

Folding hides only the PDF tools (rotate, move, split, compress, extract,
merge, annotate); close, document/group navigation, pages and zoom stay. The
toolbar becomes one slim untitled row (DV25-P2-FIX1) and the canvas or 2x2
mosaic takes exactly the freed height. Folding re-lays out the live shell: nothing is rendered again
and document, group, page, zoom and notes stay.

Synthetic PDFs in a TemporaryDirectory and Flet fakes only: no Flet client,
no database, no Box, no real documents. PDF tool handlers are mocks; no PDF
operation runs.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_notes_service as notes_service
from backend.services import document_viewer_service as service
from frontend.components import document_viewer_modal as viewer
from frontend.components import document_viewer_multidoc as multidoc
from frontend.components import document_viewer_notes_panel as panel
from frontend.components.document_viewer_modal import (
    SUPPORTED_VIEWPORTS, TOOLS_LABEL, TOOLS_TOGGLE, open_document_viewer_modal,
    viewer_action_buttons, viewer_action_label, viewer_active_document, viewer_layout,
    viewer_metrics,
)
from frontend.components.pdf_tools_toolbar_adapter import PDF_ACTIONS, PdfToolsToolbarAdapter


TOOL_LABELS = [label for _, label in PDF_ACTIONS]
OPERATIONS = {operation for operation, _ in PDF_ACTIONS}
KEPT = ["Anterior", "Siguiente", "Zoom -", "Zoom +", "Abrir con visor del sistema", "Cerrar"]
PAGES = 6


def walk(control):
    yield control
    for name in ("content", "title"):
        child = getattr(control, name, None)
        if isinstance(child, ft.Control):
            yield from walk(child)
    for child in getattr(control, "controls", None) or ():
        yield from walk(child)


def contains(root, control):
    return any(item is control for item in walk(root))


def row_width(row):
    """Fixed width of the toolbar row, as laid out without stretching (DV23)."""
    total = 0
    for child in row.controls:
        if isinstance(child, ft.Column):
            commands = child.controls[1]
            widths = [c.width for c in commands.controls]
            total += sum(widths) + commands.spacing * (len(widths) - 1)
        else:
            margin = child.margin.left + child.margin.right if child.margin else 0
            total += child.width + margin
    return total


class ToolbarBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.docs = []
        for index in range(5):
            path = self.root / f"doc{index}.pdf"
            with fitz.open() as document:
                for number in range(PAGES):
                    document.new_page(width=150, height=150).insert_text(
                        (20, 30), f"doc{index} p{number + 1}")
                document.save(path)
            self.docs.append(path)
        self.originals = {path: path.read_bytes() for path in self.docs}
        patcher = patch.object(service, "PREVIEW_DIR", self.root / "previews")
        patcher.start()
        self.addCleanup(patcher.stop)
        # The session preference is process memory: every test starts unfolded.
        preference = patch.dict(viewer._TOOLS_PREFERENCE, {"collapsed": False})
        preference.start()
        self.addCleanup(preference.stop)
        self.handlers = {"rotate": Mock(), "split": Mock()}
        self.item = {"id": 7, "stored_path": str(self.docs[0])}

    def tearDown(self):
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content, path)

    def page(self, size=(1366, 768)):
        page = SimpleNamespace(overlay=[], update=Mock())
        page.width, page.height = size
        return page

    def adapter(self):
        return PdfToolsToolbarAdapter(lambda request: self.item, self.handlers, Mock())

    def open(self, size=(1366, 768), queue_size=0, page=None, **kwargs):
        self.viewer_page = page or self.page(size)
        queue = [{"path": str(path), "name": path.name} for path in self.docs[:queue_size]]
        kwargs.setdefault("toolbar_actions", self.adapter())
        kwargs.setdefault("near_window", 0)
        return open_document_viewer_modal(self.viewer_page, str(self.docs[0]), title=self.docs[0].name,
                                          queue=queue, **kwargs)

    def labels(self, dialog):
        return [viewer_action_label(b) for b in viewer_action_buttons(dialog)]

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def toggle(self, dialog):
        source = viewer_layout(dialog).tools_toggle
        self.assertIsNotNone(source)
        source.on_click(None)
        return source

    def row(self, dialog):
        (toolbar,) = dialog.actions
        return toolbar.content

    def assert_geometry(self, dialog, folded, strip=0):
        layout = viewer_layout(dialog)
        metrics = layout.metrics
        height = metrics.canvas_height_for(folded) - strip
        self.assertIs(layout.tools_collapsed, folded)
        self.assertEqual(dialog.content.height, strip + metrics.info_height + 10 + height)
        row = self.row(dialog)
        self.assertEqual(row_width(row), metrics.content_width - 26)
        separators = [c for c in row.controls
                      if not isinstance(c, ft.Column) and c.width == 1 and c.bgcolor == viewer.Q_BORDER]
        expected = (metrics.FOLDED_COMMAND_HEIGHT if folded
                    else metrics.tile_height + metrics.GROUP_TITLE)
        self.assertTrue(separators and all(s.height == expected for s in separators))
        return height

    def assert_slim_band(self, dialog):
        """Folded band: one untitled row of slim commands, slim padding."""
        metrics = viewer_layout(dialog).metrics
        (toolbar,) = dialog.actions
        self.assertEqual(toolbar.padding.top + toolbar.padding.bottom, 2 * metrics.FOLDED_PAD)
        groups = [c for c in toolbar.content.controls if isinstance(c, ft.Column)]
        self.assertTrue(groups)
        for group in groups:
            heading, commands = group.controls
            self.assertFalse(heading.visible)
            self.assertEqual((heading.height, group.spacing), (0, 0))
            for command in commands.controls:
                self.assertEqual(command.height, metrics.FOLDED_COMMAND_HEIGHT)
        self.assertEqual(viewer_layout(dialog).tools_toggle.height, metrics.FOLDED_COMMAND_HEIGHT)

    def assert_folded(self, dialog):
        layout = viewer_layout(dialog)
        toggle = layout.tools_toggle
        self.assertEqual(viewer_action_label(toggle), TOOLS_LABEL)
        self.assertEqual(toggle.data, TOOLS_TOGGLE)
        self.assertIn("plegadas", toggle.tooltip)
        self.assertTrue(contains(dialog.actions[0], toggle))
        self.assertFalse(set(TOOL_LABELS) & set(self.labels(dialog)))
        self.assertFalse([c for c in walk(dialog.actions[0]) if getattr(c, "data", None) in OPERATIONS])
        for label in KEPT:
            self.assertTrue(contains(dialog.actions[0], self.button(dialog, label)), label)
        self.assertFalse(self.button(dialog, "Cerrar").disabled)

    def assert_unfolded(self, dialog):
        layout = viewer_layout(dialog)
        toggle = layout.tools_toggle
        self.assertEqual(toggle.data, TOOLS_TOGGLE)
        self.assertIn("desplegadas", toggle.tooltip)
        self.assertTrue(contains(dialog.actions[0], toggle))
        self.assertEqual(self.labels(dialog)[:len(TOOL_LABELS)], TOOL_LABELS)
        for label in TOOL_LABELS + KEPT:
            self.assertTrue(contains(dialog.actions[0], self.button(dialog, label)), label)


class MetricsTests(unittest.TestCase):
    def test_folded_band_frees_height_for_the_canvas_at_every_resolution(self):
        for width, height in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=(width, height)):
                metrics = viewer_metrics(width, height)
                freed = metrics.toolbar_height - metrics.toolbar_height_for(True)
                # The whole titled band folds, not just the tile-to-command difference.
                self.assertEqual(metrics.toolbar_height_for(True),
                                 metrics.FOLDED_COMMAND_HEIGHT + 2 * metrics.FOLDED_PAD)
                self.assertGreater(freed, metrics.tile_height - metrics.COMMAND_HEIGHT)
                self.assertGreaterEqual(freed, 56)
                self.assertEqual(metrics.canvas_height_for(True), metrics.canvas_height + freed)
                self.assertEqual(metrics.canvas_height_for(False), metrics.canvas_height)
                # Both states keep the shell within the screen and the toolbar unclipped.
                self.assertLessEqual(metrics.total_height + 2 * metrics.inset_v, height)
                self.assertLessEqual(metrics.toolbar_width(len(PDF_ACTIONS)), metrics.content_width)
                self.assertLessEqual(metrics.toolbar_width(0, folded=True), metrics.content_width)


class SingleModeTests(ToolbarBase):
    def test_default_is_unfolded_with_accessible_toggle(self):
        dialog = self.open()
        self.assert_unfolded(dialog)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.canvas.height, layout.metrics.canvas_height)
        self.assert_geometry(dialog, False)
        # The toggle is not one of the historical commands (DV23 order intact).
        self.assertFalse(any(b is layout.tools_toggle for b in viewer_action_buttons(dialog)))

    def test_repeated_folding_at_each_resolution_resizes_without_rendering(self):
        for size in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=size):
                dialog = self.open(size)
                layout = viewer_layout(dialog)
                canvas, list_view = layout.canvas, layout.canvas.content
                with patch.object(service, "create_document_preview",
                                  wraps=service.create_document_preview) as render:
                    for _ in range(3):
                        self.toggle(dialog)
                        self.assert_folded(dialog)
                        height = self.assert_geometry(dialog, True)
                        self.assertEqual(canvas.height, height)
                        self.toggle(dialog)
                        self.assert_unfolded(dialog)
                        self.assertEqual(canvas.height, self.assert_geometry(dialog, False))
                render.assert_not_called()
                # Same shell, canvas and page window: the panel is resized, not rebuilt.
                self.assertIs(viewer_layout(dialog), layout)
                self.assertIs(layout.canvas.content, list_view)
                self.assertEqual(layout.page_label.value, f"Página 1 de {PAGES}")
                self.button(dialog, "Cerrar").on_click(None)
                self.assertFalse(dialog.open)

    def test_folding_keeps_page_zoom_and_navigation(self):
        dialog = self.open(initial_page=3)
        self.button(dialog, "Zoom +").on_click(None)
        self.toggle(dialog)
        layout = viewer_layout(dialog)
        self.assertEqual((layout.page_label.value, layout.zoom_label.value),
                         (f"Página 3 de {PAGES}", "Zoom: 2.0x"))
        # Navigation and zoom work while folded and the band stays folded.
        self.button(dialog, "Siguiente").on_click(None)
        self.button(dialog, "Zoom -").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual((layout.page_label.value, layout.zoom_label.value),
                         (f"Página 4 de {PAGES}", "Zoom: 1.6x"))
        self.assert_folded(dialog)
        self.assertEqual(layout.canvas.height, self.assert_geometry(dialog, True))
        self.toggle(dialog)
        self.assert_unfolded(dialog)
        self.assertEqual(viewer_layout(dialog).page_label.value, f"Página 4 de {PAGES}")

    def test_tools_work_after_unfolding_and_stale_commands_are_inert(self):
        dialog = self.open()
        old_tile = self.button(dialog, "Rotar páginas")
        old_toggle = self.toggle(dialog)
        # The replaced toggle and tool tiles no longer act.
        old_toggle.on_click(None)
        old_tile.on_click("old")
        self.assert_folded(dialog)
        self.handlers["rotate"].assert_not_called()
        self.toggle(dialog)
        self.button(dialog, "Rotar páginas").on_click("evt")
        self.handlers["rotate"].assert_called_once_with("evt", item_id=7)

    def test_scroll_republish_keeps_the_fold(self):
        dialog = self.open(near_window=1)
        self.toggle(dialog)
        layout = viewer_layout(dialog)
        slot = int(1000 * 1.6) + 48
        layout.canvas.content.on_scroll(SimpleNamespace(pixels=2 * slot + 10))
        self.assertEqual(viewer_layout(dialog).page_label.value, f"Página 3 de {PAGES}")
        self.assert_folded(dialog)
        self.assert_geometry(dialog, True)

    def test_queue_navigation_keeps_the_fold_and_the_strip(self):
        dialog = self.open(queue_size=3)
        strip = multidoc.strip_height(viewer_layout(dialog).metrics) + 10
        self.toggle(dialog)
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(viewer_active_document(dialog).index, 1)
        self.assert_folded(dialog)
        self.assertEqual(viewer_layout(dialog).canvas.height, self.assert_geometry(dialog, True, strip))

    def test_without_tool_factory_there_is_nothing_to_fold(self):
        viewer._TOOLS_PREFERENCE["collapsed"] = True
        dialog = self.open(toolbar_actions=None)
        layout = viewer_layout(dialog)
        self.assertIsNone(layout.tools_toggle)
        self.assertFalse(layout.tools_collapsed)
        self.assertEqual(layout.canvas.height, layout.metrics.canvas_height)
        self.assertEqual(self.labels(dialog), KEPT)

    def test_failed_preview_still_offers_unfolding(self):
        viewer._TOOLS_PREFERENCE["collapsed"] = True
        page = self.page()
        dialog = open_document_viewer_modal(page, str(self.root / "missing.pdf"),
                                            toolbar_actions=self.adapter())
        self.assertEqual(viewer_action_label(viewer_layout(dialog).tools_toggle), TOOLS_LABEL)
        self.toggle(dialog)
        # Unfolded without tools: the DV23 toolbar, nothing left to fold.
        self.assertIsNone(viewer_layout(dialog).tools_toggle)
        self.assertEqual(self.labels(dialog), KEPT)


class SessionPreferenceTests(ToolbarBase):
    def test_reopening_restores_last_fold_and_recomputes_for_the_new_size(self):
        dialog = self.open((1920, 1080))
        self.toggle(dialog)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(viewer._TOOLS_PREFERENCE, {"collapsed": True})
        # Reopen in a smaller window ("resize"): folded, with that window's geometry.
        for size in ((1366, 768), (1600, 900)):
            with self.subTest(viewport=size):
                dialog = self.open(size)
                layout = viewer_layout(dialog)
                self.assertEqual(layout.metrics.viewport, size)
                self.assert_folded(dialog)
                self.assertEqual(layout.canvas.height, self.assert_geometry(dialog, True))
                self.button(dialog, "Cerrar").on_click(None)
        dialog = self.open()
        self.toggle(dialog)
        self.button(dialog, "Cerrar").on_click(None)
        self.assert_unfolded(self.open())

    def test_preference_holds_only_the_fold_flag(self):
        dialog = self.open()
        self.toggle(dialog)
        self.assertEqual(viewer._TOOLS_PREFERENCE, {"collapsed": True})

    def test_fast_close_after_folding_drops_late_toggles(self):
        dialog = self.open()
        toggle = self.toggle(dialog)
        self.button(dialog, "Cerrar").on_click(None)
        updates = self.viewer_page.update.call_count
        toggle.on_click(None)
        self.assertIsNone(dialog.content)
        self.assertEqual(dialog.actions, [])
        self.assertEqual(self.viewer_page.update.call_count, updates)
        self.assertEqual(viewer._TOOLS_PREFERENCE, {"collapsed": True})
        self.assertEqual(list((self.root / "previews").rglob("*.png")), [])


class ComparatorTests(ToolbarBase):
    def compare(self, dialog):
        self.button(dialog, "Comparador 4").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
        return layout

    def test_mosaic_takes_the_freed_height_without_rendering(self):
        for size in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=size):
                dialog = self.open(size, queue_size=5)
                layout = self.compare(dialog)
                strip = multidoc.strip_height(layout.metrics) + 10
                layout.tiles[1].container.on_click(None)  # second tile becomes active
                self.button(dialog, "Siguiente").on_click(None)
                before = viewer_layout(dialog)
                state = ([t.page for t in before.comparator.tiles], before.document.index,
                         before.group_label.value)
                tile_height = before.tiles[0].container.height
                with patch.object(service, "create_document_preview",
                                  wraps=service.create_document_preview) as render:
                    self.toggle(dialog)
                    self.assert_folded(dialog)
                    height = self.assert_geometry(dialog, True, strip)
                    after = viewer_layout(dialog)
                    self.assertEqual(after.canvas.height, height)
                    self.assertGreater(after.tiles[0].container.height, tile_height)
                    self.assertEqual(([t.page for t in after.comparator.tiles], after.document.index,
                                      after.group_label.value), state)
                    for label in ("Grupo anterior", "Grupo siguiente", "Documento único"):
                        self.assertIn(label, self.labels(dialog))
                    self.toggle(dialog)
                    self.assert_unfolded(dialog)
                    self.assert_geometry(dialog, False, strip)
                render.assert_not_called()
                self.assertLessEqual(after.comparator.live_sessions(), multidoc.GROUP_SIZE)
                self.assertEqual(viewer_layout(dialog).tiles[0].container.height, tile_height)
                self.button(dialog, "Cerrar").on_click(None)

    def test_fold_survives_group_and_mode_changes(self):
        dialog = self.open(queue_size=5)
        self.toggle(dialog)
        strip = multidoc.strip_height(viewer_layout(dialog).metrics) + 10
        self.compare(dialog)
        self.assert_folded(dialog)
        self.assert_geometry(dialog, True, strip)
        self.button(dialog, "Grupo siguiente").on_click(None)
        self.assertEqual(viewer_layout(dialog).group_label.value, "Grupo 2 de 2")
        self.assert_folded(dialog)
        self.button(dialog, "Documento único").on_click(None)
        self.assertEqual(viewer_layout(dialog).mode, multidoc.MODE_SINGLE)
        self.assert_folded(dialog)
        self.assert_geometry(dialog, True, strip)

    def test_tools_act_on_the_active_document_after_unfolding(self):
        dialog = self.open(queue_size=3)
        self.compare(dialog)
        old_toggle = self.toggle(dialog)
        self.toggle(dialog)
        old_toggle.on_click(None)  # stale: the band stays unfolded
        self.assert_unfolded(dialog)
        self.button(dialog, "Rotar páginas").on_click("evt")
        self.handlers["rotate"].assert_called_once_with("evt", item_id=7)


class FoldedSpaceTests(ToolbarBase):
    """DV25-P2-FIX1: height the folded band really gives to the canvas.

    P2 freed only 14 px (1366x768) or 22 px (1600x900, 1920x1080).
    """
    FREED = {(1366, 768): 56, (1600, 900): 64, (1920, 1080): 64}

    def test_single_mode_canvas_gains_the_whole_titled_band(self):
        for size, freed in self.FREED.items():
            with self.subTest(viewport=size):
                dialog = self.open(size)
                layout = viewer_layout(dialog)
                canvas, shell = layout.canvas.height, dialog.content.height
                self.toggle(dialog)
                self.assert_slim_band(dialog)
                self.assertEqual(layout.canvas.height - canvas, freed)
                self.assertEqual(dialog.content.height - shell, freed)
                # Navigation, zoom, active document and close stay usable.
                self.assert_folded(dialog)
                self.button(dialog, "Siguiente").on_click(None)
                self.assertEqual(viewer_layout(dialog).page_label.value, f"Página 2 de {PAGES}")
                self.assert_slim_band(dialog)
                self.toggle(dialog)
                self.assertEqual(viewer_layout(dialog).canvas.height, canvas)
                self.button(dialog, "Cerrar").on_click(None)
                self.assertFalse(dialog.open)

    def test_comparator_tiles_gain_half_the_band_each(self):
        for size, freed in self.FREED.items():
            with self.subTest(viewport=size):
                dialog = self.open(size, queue_size=4)
                self.button(dialog, "Comparador 4").on_click(None)
                # Viewer preference persists across dialogs. Start each viewport
                # from the expanded state before measuring its folded gain.
                if viewer_layout(dialog).tools_collapsed:
                    self.toggle(dialog)
                self.assertFalse(viewer_layout(dialog).tools_collapsed)
                before = viewer_layout(dialog)
                canvas, tile = before.canvas.height, before.tiles[0].container.height
                with patch.object(service, "create_document_preview",
                                  wraps=service.create_document_preview) as render:
                    self.toggle(dialog)
                render.assert_not_called()
                after = viewer_layout(dialog)
                self.assert_slim_band(dialog)
                self.assertEqual(after.canvas.height - canvas, freed)
                # Two rows of tiles share the freed height.
                self.assertGreaterEqual(after.tiles[0].container.height - tile, freed // 2 - 1)
                self.assertLessEqual(after.comparator.live_sessions(), multidoc.GROUP_SIZE)
                self.button(dialog, "Cerrar").on_click(None)


class NotesTests(ToolbarBase):
    def setUp(self):
        super().setUp()
        # Expediente 42 is synthetic: its document root is the temporary folder,
        # so previews (and the PDF tools that depend on them) are real.
        root = patch.object(service, "get_expediente_document_root",
                            return_value={"expediente_id": 42, "root_path": str(self.root),
                                          "exists": True, "message": ""})
        root.start()
        self.addCleanup(root.stop)

    def notes_data(self):
        identity = SimpleNamespace(label="Documento sintético", description="", content_sha256="0" * 64)
        return {"identity": identity, "notes": [], "user": {"id": 1, "username": "tester"},
                "activity": []}

    def test_folding_keeps_notes_and_resizes_the_panel(self):
        notes = panel.ViewerNotes(actor={"id": 1, "username": "tester"}, run=lambda work: work())
        with patch.object(notes_service, "load_document_notes",
                          side_effect=lambda *a, **k: self.notes_data()) as load:
            dialog = self.open(expediente_id=42, notes=notes)
            controller = viewer_layout(dialog).notes
            unfolded = controller.container.height
            controller.field.value = "borrador"  # typed by the user
            controller.field.on_change(SimpleNamespace(control=controller.field))
            for folded in (True, False, True):
                self.toggle(dialog)
                layout = viewer_layout(dialog)
                self.assertIs(layout.notes, controller)
                self.assertEqual(controller.container.height, layout.canvas.height)
                self.assertEqual(layout.canvas.height, self.assert_geometry(dialog, folded))
                self.assertEqual(controller.container.height - unfolded,
                                 FoldedSpaceTests.FREED[(1366, 768)] if folded else 0)
                self.assertEqual(controller.state.draft, "borrador")
                self.assertEqual(controller.field.value, "borrador")
            load.assert_called_once()

    def test_outside_the_expediente_there_is_no_toggle(self):
        # A document outside the expediente root has no preview, hence no PDF
        # tools: the toggle is absent, not forced.
        outside = self.root / "outside"
        with patch.object(service, "get_expediente_document_root",
                          return_value={"root_path": str(outside), "exists": True, "message": ""}), \
                patch.object(notes_service, "load_document_notes",
                             side_effect=lambda *a, **k: self.notes_data()):
            outside.mkdir()
            notes = panel.ViewerNotes(actor={"id": 1, "username": "tester"}, run=lambda work: work())
            dialog = self.open(expediente_id=42, notes=notes)
        layout = viewer_layout(dialog)
        self.assertIsNone(layout.tools_toggle)
        self.assertFalse(layout.tools_collapsed)
        self.assertEqual(self.labels(dialog), KEPT)


if __name__ == "__main__":
    unittest.main()
