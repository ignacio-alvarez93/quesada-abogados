"""WO-DV31-01: the viewer's blue header folds into a slim band.

Synthetic PDFs and images in temporary directories only; no Flet client,
no CRM database, no Box. The freed height must really reach the canvas or
the comparator mosaic, independently of the PDF tools fold and the notes
panel, without rendering again or touching document state.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_actions_service as actions_service
from backend.services import document_viewer_service as service
from frontend.components import document_viewer_actions_panel as panel
from frontend.components import document_viewer_modal as viewer
from frontend.components import document_viewer_multidoc as multidoc
from frontend.components.document_viewer_modal import (
    HEADER_TOGGLE, SUPPORTED_VIEWPORTS, open_document_viewer_modal, viewer_action_buttons,
    viewer_action_label, viewer_layout, viewer_metrics,
)
from frontend.components.document_viewer_notes_panel import ViewerNotes
from frontend.components.pdf_tools_toolbar_adapter import PdfToolsToolbarAdapter


PAGES = 25
BRAND = "Quesada Abogados"


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


def contains(root, control):
    return any(c is control for c in walk(root))


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


class HeaderBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.docs = []
        for index in range(5):
            path = self.root / f"doc{index}.pdf"
            with fitz.open() as document:
                for number in range(PAGES):
                    document.new_page(width=595, height=842).insert_text(
                        (72, 72), f"doc{index} p{number + 1}", fontsize=24)
                document.save(path)
            self.docs.append(path)
        self.image = self.root / "foto.png"
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 48), False)
        pixmap.clear_with(200)
        pixmap.save(str(self.image))
        self.originals = {path: path.read_bytes() for path in self.docs + [self.image]}
        # expediente_id=1 resolves to the temporary folder, never the CRM database.
        root = {"exists": True, "root_path": str(self.root), "message": ""}
        # Both session preferences are process memory: every test starts unfolded.
        for patcher in (patch.object(service, "PREVIEW_DIR", self.root / "previews"),
                        patch.object(service, "get_expediente_document_root", return_value=root),
                        patch.dict(viewer._TOOLS_PREFERENCE, {"collapsed": False}),
                        patch.dict(viewer._HEADER_PREFERENCE, {"collapsed": False})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.item = {"id": 7, "stored_path": str(self.docs[0])}

    def tearDown(self):
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content, path)

    def adapter(self):
        return PdfToolsToolbarAdapter(lambda request: self.item, {"rotate": Mock()}, Mock())

    def notes(self):
        # Loads are never run: geometry and drafts are what is checked here.
        return ViewerNotes(actor={"id": 1, "username": "tester"}, run=lambda work: None)

    def queue(self, count=4):
        return [{"path": str(path), "name": path.name} for path in self.docs[:count]]

    def open(self, size=(1366, 768), path=None, page=None, **kwargs):
        self.viewer_page = page or ModernPage(size)
        kwargs.setdefault("dialog", MountedDialog(modal=True))
        kwargs.setdefault("near_window", 1)
        kwargs.setdefault("expediente_id", 1)
        source = path or self.docs[0]
        return open_document_viewer_modal(self.viewer_page, str(source), title=Path(source).name,
                                          **kwargs)

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def fold_header(self, dialog):
        source = viewer_layout(dialog).header_toggle
        self.assertIsNotNone(source)
        source.on_click(None)
        return source

    def fold_tools(self, dialog):
        viewer_layout(dialog).tools_toggle.on_click(None)

    @staticmethod
    def freed(metrics):
        return metrics.header_height - metrics.COLLAPSED_HEADER_HEIGHT

    def assert_header(self, dialog, collapsed):
        layout = viewer_layout(dialog)
        metrics = layout.metrics
        title = dialog.title
        self.assertIs(layout.header_collapsed, collapsed)
        self.assertEqual(title.width, metrics.outer_width)
        self.assertEqual(title.height, metrics.header_height_for(collapsed))
        # Toggle: accessible, inside the header, never a toolbar command.
        toggle = layout.header_toggle
        self.assertEqual(toggle.data, HEADER_TOGGLE)
        self.assertTrue(callable(toggle.on_click))
        self.assertIn("desplegar cabecera" if collapsed else "plegar cabecera", toggle.tooltip)
        self.assertTrue(contains(title, toggle))
        self.assertFalse(any(b is toggle for b in viewer_action_buttons(dialog)))
        self.assertFalse(contains(dialog.actions[0], toggle))
        # Cerrar visor: always there, and the header's only icon button.
        close = layout.header_close
        icon_buttons = [c for c in walk(title) if isinstance(c, ft.IconButton)]
        self.assertEqual(len(icon_buttons), 1)
        self.assertIs(icon_buttons[0], close)
        self.assertEqual((close.icon, close.tooltip), (ft.Icons.CLOSE, "Cerrar visor"))
        self.assertIsNotNone(close.on_click)
        self.assertTrue(close.height is None or close.height <= title.height)
        self.assertTrue(toggle.height <= title.height)
        # The document name stays, truncable.
        self.assertTrue(contains(title, layout.title))
        self.assertEqual(layout.title.overflow, ft.TextOverflow.ELLIPSIS)
        self.assertEqual(layout.title.max_lines, 1)
        header_texts = texts(title)
        if collapsed:
            self.assertNotIn(BRAND, header_texts)
            self.assertNotIn("Visor documental", header_texts)
        else:
            self.assertEqual(header_texts[:1], ["Visor documental"])
            self.assertIn(BRAND, header_texts)

    def assert_single_geometry(self, dialog, folded=False, collapsed=False, strip=0):
        layout = viewer_layout(dialog)
        metrics = layout.metrics
        height = metrics.canvas_height_for(folded, collapsed) - strip
        self.assertEqual(layout.canvas.height, height)
        self.assertEqual(dialog.content.height, strip + metrics.info_height + 10 + height)
        self.assertEqual(dialog.content.width, metrics.content_width)
        if layout.notes is not None:
            self.assertEqual(layout.notes.container.height, height)
        # The whole shell keeps filling the same viewport.
        self.assertEqual(
            metrics.header_height_for(collapsed) + dialog.content.height - strip
            - metrics.info_height - 10 + metrics.toolbar_height_for(folded),
            metrics.header_height + metrics.canvas_height + metrics.toolbar_height)
        return height


class MetricsTests(unittest.TestCase):
    def test_header_fold_adds_its_freed_height_once_at_each_resolution(self):
        for width, height in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=(width, height)):
                metrics = viewer_metrics(width, height)
                self.assertEqual(metrics.header_height_for(False), metrics.header_height)
                self.assertEqual(metrics.header_height_for(True), 36)
                header = metrics.header_height - 36
                tools = metrics.toolbar_height - metrics.toolbar_height_for(True)
                self.assertEqual(header, 24 if metrics.compact else 36)
                # DV25/DV30 budget unchanged; the header fold is additive.
                self.assertEqual(metrics.canvas_height_for(False), metrics.canvas_height)
                self.assertEqual(metrics.canvas_height_for(True), metrics.canvas_height + tools)
                self.assertEqual(metrics.canvas_height_for(False, True), metrics.canvas_height + header)
                self.assertEqual(metrics.canvas_height_for(True, True),
                                 metrics.canvas_height + tools + header)
                self.assertEqual(metrics.total_height + 2 * metrics.inset_v, height)
                for folded in (False, True):
                    for collapsed in (False, True):
                        self.assertEqual(
                            metrics.header_height_for(collapsed)
                            + metrics.canvas_height_for(folded, collapsed)
                            + metrics.toolbar_height_for(folded),
                            metrics.header_height + metrics.canvas_height + metrics.toolbar_height)


class SingleModeTests(HeaderBase):
    def test_first_opening_is_unfolded_like_dv30(self):
        dialog = self.open((1600, 900), toolbar_actions=self.adapter())
        self.assert_header(dialog, False)
        self.assert_single_geometry(dialog)
        self.assertFalse(viewer_layout(dialog).tools_collapsed)

    def test_folding_grows_the_canvas_in_place_at_each_resolution(self):
        for size in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=size):
                dialog = self.open(size, toolbar_actions=self.adapter(), notes=self.notes())
                layout = viewer_layout(dialog)
                canvas, list_view = layout.canvas, layout.canvas.content
                original = canvas.height
                updates = self.viewer_page.update.call_count
                with patch.object(service, "create_document_preview") as render:
                    for _ in range(2):
                        old_toggle = self.fold_header(dialog)
                        self.assert_header(dialog, True)
                        height = self.assert_single_geometry(dialog, collapsed=True)
                        self.assertEqual(height, original + self.freed(layout.metrics))
                        # The replaced toggle is stale: nothing changes.
                        old_toggle.on_click(None)
                        self.assert_header(dialog, True)
                        self.fold_header(dialog)
                        self.assert_header(dialog, False)
                        self.assertEqual(self.assert_single_geometry(dialog), original)
                    render.assert_not_called()
                self.assertEqual(self.viewer_page.update.call_count, updates)
                self.assertIs(viewer_layout(dialog), layout)
                self.assertIs(layout.canvas, canvas)
                self.assertIs(canvas.content, list_view)
                layout.header_close.on_click(None)
                self.assertFalse(dialog.open)

    def test_header_and_tools_folds_add_up_without_double_counting(self):
        dialog = self.open((1920, 1080), toolbar_actions=self.adapter(), notes=self.notes())
        metrics = viewer_layout(dialog).metrics
        tools = metrics.toolbar_height - metrics.toolbar_height_for(True)
        base = viewer_layout(dialog).canvas.height
        self.fold_tools(dialog)
        self.assertEqual(self.assert_single_geometry(dialog, folded=True), base + tools)
        self.fold_header(dialog)
        self.assertTrue(viewer_layout(dialog).tools_collapsed)
        self.assert_header(dialog, True)
        self.assertEqual(self.assert_single_geometry(dialog, folded=True, collapsed=True),
                         base + tools + self.freed(metrics))
        # Each toggle only moves its own fold.
        self.fold_tools(dialog)
        self.assertTrue(viewer_layout(dialog).header_collapsed)
        self.assertFalse(viewer_layout(dialog).tools_collapsed)
        self.assertEqual(self.assert_single_geometry(dialog, collapsed=True),
                         base + self.freed(metrics))
        self.fold_header(dialog)
        self.assertEqual(self.assert_single_geometry(dialog), base)
        # Repeated resizes while both are folded recompute from scratch.
        self.fold_tools(dialog)
        self.fold_header(dialog)
        for size in ((1366, 768), (1600, 900), (1366, 768)):
            self.viewer_page.on_resize(resize_event(*size))
            resized = viewer_layout(dialog).metrics
            self.assertEqual(resized.viewport, size)
            self.assert_header(dialog, True)
            self.assertEqual(self.assert_single_geometry(dialog, folded=True, collapsed=True),
                             resized.canvas_height_for(True) + self.freed(resized))

    def test_folding_keeps_page_zoom_scroll_notes_and_document(self):
        dialog = self.open((1366, 768), initial_page=4, toolbar_actions=self.adapter(),
                           notes=self.notes())
        self.button(dialog, "Zoom +").on_click(None)
        layout = viewer_layout(dialog)
        list_view = layout.canvas.content
        spacer = list_view.controls[0].height
        notes = layout.notes
        notes_container = notes.container
        notes.state.draft = "borrador sin enviar"
        document = layout.document
        session = dialog.data
        self.fold_header(dialog)
        layout = viewer_layout(dialog)
        self.assertIs(dialog.data, session)
        self.assertIs(layout.document, document)
        self.assertEqual(layout.page_label.value, f"Página 4 de {PAGES}")
        self.assertEqual(layout.zoom_label.value, "Zoom: 2.0x")
        self.assertIs(layout.canvas.content, list_view)
        self.assertEqual(list_view.controls[0].height, spacer)
        self.assertIs(notes.container, notes_container)
        self.assertFalse(notes.collapsed)
        self.assertEqual(notes.state.draft, "borrador sin enviar")
        self.assertFalse(layout.tools_collapsed)
        # Navigation keeps the folded header and builds with the freed height.
        self.button(dialog, "Siguiente").on_click(None)
        self.assertEqual(viewer_layout(dialog).page_label.value, f"Página 5 de {PAGES}")
        self.assert_header(dialog, True)
        self.assert_single_geometry(dialog, collapsed=True)
        self.fold_header(dialog)
        self.assertEqual(viewer_layout(dialog).zoom_label.value, "Zoom: 2.0x")
        self.assertEqual(notes.state.draft, "borrador sin enviar")

    def test_queue_navigation_keeps_the_fold_and_the_strip(self):
        dialog = self.open((1600, 900), queue=self.queue(3))
        strip = multidoc.strip_height(viewer_layout(dialog).metrics) + 10
        self.fold_header(dialog)
        self.button(dialog, "Doc siguiente").on_click(None)
        self.assertEqual(viewer_layout(dialog).document.index, 1)
        self.assert_header(dialog, True)
        self.assert_single_geometry(dialog, collapsed=True, strip=strip)

    def test_image_canvas_takes_the_freed_height(self):
        dialog = self.open((1600, 900), path=self.image)
        original = viewer_layout(dialog).canvas.height
        self.fold_header(dialog)
        self.assert_header(dialog, True)
        self.assertEqual(self.assert_single_geometry(dialog, collapsed=True),
                         original + self.freed(viewer_layout(dialog).metrics))

    def test_close_from_the_folded_header(self):
        crm = Mock()
        page = ModernPage((1366, 768))
        page.on_resize = crm
        dialog = self.open(page=page)
        self.fold_header(dialog)
        viewer_layout(dialog).header_close.on_click(None)
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.content)
        self.assertIs(page.on_resize, crm)

    def test_folding_is_not_the_toolbar_close_or_tools_toggle(self):
        dialog = self.open(toolbar_actions=self.adapter())
        layout = viewer_layout(dialog)
        self.assertIsNot(layout.header_toggle, layout.tools_toggle)
        self.assertNotEqual(layout.header_toggle.data, layout.tools_toggle.data)
        self.assertNotIn("Herramientas", layout.header_toggle.tooltip)
        self.fold_header(dialog)
        self.assertTrue(dialog.open)
        self.assertIsNotNone(dialog.content)
        self.assertIn("Cerrar", [viewer_action_label(b) for b in viewer_action_buttons(dialog)])


class ComparatorTests(HeaderBase):
    def compare(self, dialog):
        self.button(dialog, "Comparador 4").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
        return layout

    def assert_mosaic(self, dialog, collapsed, folded=False):
        layout = viewer_layout(dialog)
        metrics = layout.metrics
        strip = multidoc.strip_height(metrics) + 10
        height = metrics.canvas_height_for(folded, collapsed) - strip
        self.assertEqual(layout.canvas.height, height)
        self.assertEqual(dialog.content.height, strip + metrics.info_height + 10 + height)
        width = metrics.content_width - (layout.notes.space if layout.notes else 0)
        for tile in layout.tiles:
            self.assertEqual(tile.container.width, (width - 10) // 2)
            self.assertEqual(tile.container.height, (height - 10) // 2)
        if layout.notes is not None:
            self.assertEqual(layout.notes.container.height, height)
        return height

    def test_mosaic_takes_the_freed_height_keeping_group_pages_and_selection(self):
        for size in SUPPORTED_VIEWPORTS:
            with self.subTest(viewport=size):
                dialog = self.open(size, queue=self.queue(5), notes=self.notes(),
                                   toolbar_actions=self.adapter())
                layout = self.compare(dialog)
                self.button(dialog, "Siguiente").on_click(None)
                layout.tiles[2].container.on_click(None)
                comparator = viewer_layout(dialog).comparator
                group = viewer_layout(dialog).group_label.value
                original = self.assert_mosaic(dialog, False)
                with patch.object(service, "create_document_preview") as render:
                    self.fold_header(dialog)
                    render.assert_not_called()
                layout = viewer_layout(dialog)
                self.assert_header(dialog, True)
                self.assertEqual(self.assert_mosaic(dialog, True),
                                 original + self.freed(layout.metrics))
                self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
                self.assertEqual(layout.group_label.value, group)
                self.assertEqual(comparator.tile_for(0).page, 2)
                self.assertEqual(layout.document.index, 2)
                self.assertEqual(len(layout.tiles), 4)
                # Tools fold on top of the header fold, then both unfold.
                self.fold_tools(dialog)
                self.assert_mosaic(dialog, True, folded=True)
                self.fold_tools(dialog)
                self.fold_header(dialog)
                self.assert_header(dialog, False)
                self.assertEqual(self.assert_mosaic(dialog, False), original)
                viewer_layout(dialog).header_close.on_click(None)
                self.assertFalse(dialog.open)

    def test_resize_while_folded_keeps_the_comparator(self):
        dialog = self.open((1600, 900), queue=self.queue(), notes=self.notes())
        self.compare(dialog)
        self.button(dialog, "Siguiente").on_click(None)
        self.fold_header(dialog)
        comparator = viewer_layout(dialog).comparator
        with patch.object(service, "create_document_preview") as render:
            self.viewer_page.on_resize(resize_event(1366, 768))
            self.viewer_page.on_resize(resize_event(1920, 1080))
            render.assert_not_called()
        layout = viewer_layout(dialog)
        self.assertEqual(layout.metrics.viewport, (1920, 1080))
        self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
        self.assertEqual(comparator.tile_for(0).page, 2)
        self.assert_header(dialog, True)
        self.assert_mosaic(dialog, True)
        # Back to single mode: same page, header still folded.
        self.button(dialog, "Documento único").on_click(None)
        self.assertEqual(viewer_layout(dialog).page_label.value, f"Página 2 de {PAGES}")
        self.assert_header(dialog, True)
        self.assert_single_geometry(dialog, collapsed=True,
                                    strip=multidoc.strip_height(layout.metrics) + 10)


class ActionsTests(HeaderBase):
    def setUp(self):
        super().setUp()
        context = SimpleNamespace(expediente_label="EXP-SINT (#1)")
        for name, kwargs in (("resolve_context", {"return_value": context}),
                             ("create_task", {"side_effect": AssertionError("create_task")}),
                             ("create_alert", {"side_effect": AssertionError("create_alert")})):
            patcher = patch.object(actions_service, name, **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.jobs = []

    def actions(self):
        return panel.ViewerActions(actor={"id": 1, "username": "tester"}, run=self.jobs.append)

    def run_jobs(self):
        while self.jobs:
            self.jobs.pop(0)()

    def assert_commands(self, dialog, visible, enabled=None):
        controller = viewer_layout(dialog).actions
        for button in (controller.task_button, controller.alert_button):
            self.assertIs(contains(dialog.title, button), visible)
            if enabled is not None:
                self.assertIs(button.disabled, not enabled)

    def test_commands_hide_when_folded_and_come_back_with_their_state(self):
        dialog = self.open((1600, 900), queue=self.queue(), actions=self.actions())
        self.assert_commands(dialog, True, enabled=False)  # still checking
        self.fold_header(dialog)
        self.assert_commands(dialog, False)
        # The check finishes while folded: nothing shows and nothing is created.
        self.run_jobs()
        self.assert_commands(dialog, False)
        self.fold_header(dialog)
        self.assert_commands(dialog, True, enabled=True)
        labels = [viewer_action_label(c) for c in walk(dialog.title)
                  if isinstance(c, ft.OutlinedButton)]
        self.assertEqual(labels, [panel.TASK_LABEL, panel.ALERT_LABEL])
        # Another document while folded: unfolded, it shows that document's check.
        self.fold_header(dialog)
        self.button(dialog, "Doc siguiente").on_click(None)
        self.fold_header(dialog)
        controller = viewer_layout(dialog).actions
        self.assertEqual(controller.document.index, 1)
        self.assert_commands(dialog, True, enabled=False)
        self.run_jobs()
        self.assert_commands(dialog, True, enabled=True)
        # Comparator: the active tile's commands follow the fold too.
        self.button(dialog, "Comparador 4").on_click(None)
        self.fold_header(dialog)
        self.assert_commands(dialog, False)
        self.fold_header(dialog)
        self.assert_commands(dialog, True, enabled=True)
        self.assertEqual(self.resolve_context.call_count, 2)
        self.create_task.assert_not_called()
        self.create_alert.assert_not_called()
        self.assertIsNone(controller.form)
        viewer_layout(dialog).header_close.on_click(None)
        self.assertTrue(controller.closed)


class SessionPreferenceTests(HeaderBase):
    def test_reopening_restores_the_fold_during_the_session(self):
        dialog = self.open((1920, 1080))
        self.fold_header(dialog)
        viewer_layout(dialog).header_close.on_click(None)
        self.assertEqual(viewer._HEADER_PREFERENCE, {"collapsed": True})
        self.assertEqual(viewer._TOOLS_PREFERENCE, {"collapsed": False})
        for size in ((1366, 768), (1600, 900)):
            with self.subTest(viewport=size):
                dialog = self.open(size)
                self.assertEqual(viewer_layout(dialog).metrics.viewport, size)
                self.assert_header(dialog, True)
                self.assert_single_geometry(dialog, collapsed=True)
                self.button(dialog, "Cerrar").on_click(None)
        dialog = self.open()
        self.fold_header(dialog)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(viewer._HEADER_PREFERENCE, {"collapsed": False})
        self.assert_header(self.open(), False)

    def test_late_toggles_of_closed_or_replaced_viewers_are_inert(self):
        dialog = self.open()
        toggle = viewer_layout(dialog).header_toggle
        self.button(dialog, "Cerrar").on_click(None)
        updates = self.viewer_page.update.call_count
        toggle.on_click(None)
        self.assertIsNone(dialog.content)
        self.assertEqual(dialog.actions, [])
        self.assertEqual(self.viewer_page.update.call_count, updates)
        self.assertEqual(viewer._HEADER_PREFERENCE, {"collapsed": False})
        # A viewer reopened on the same dialog ignores its predecessor's toggle.
        page = ModernPage((1366, 768))
        reused = MountedDialog(modal=True)
        self.open(page=page, dialog=reused)
        stale = viewer_layout(reused).header_toggle
        self.open(page=page, dialog=reused)
        stale.on_click(None)
        self.assert_header(reused, False)
        self.assertEqual(viewer._HEADER_PREFERENCE, {"collapsed": False})
        reused.on_dismiss(None)
        self.assertIsNone(reused.content)

    def test_preference_holds_only_the_fold_flag(self):
        dialog = self.open()
        self.fold_header(dialog)
        self.assertEqual(viewer._HEADER_PREFERENCE, {"collapsed": True})


if __name__ == "__main__":
    unittest.main()
