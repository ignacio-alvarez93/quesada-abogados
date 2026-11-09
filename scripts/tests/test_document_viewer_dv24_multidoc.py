"""WO-DV24-P1: queue navigation and the four-document comparator.

Synthetic PDFs in a TemporaryDirectory and Flet fakes only: no Flet client,
no database, no Box, no real documents. PDF tool handlers are mocks or open
forms without submitting them, so no PDF operation runs.
"""
import ast
import inspect
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from frontend.components import document_viewer_multidoc as multidoc
from frontend.components.app_button import secondary_button
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label,
    viewer_active_document, viewer_layout,
)
from frontend.components.document_viewer_pdf_tools import PdfToolForm, ViewerPdfTools
from frontend.components.pdf_tools_toolbar_adapter import PDF_ACTIONS, PdfToolsToolbarAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPEDIENTS = REPO_ROOT / "frontend" / "views" / "expedients_view.py"
INBOX = REPO_ROOT / "frontend" / "views" / "document_inbox_view.py"
INBOX_FUNCTIONS = ("selected_item", "after_viewer_pdf_tool", "pdf_toolbar_for_item",
                   "inbox_viewer_options", "show_preview", "detail_show_preview",
                   "show_batch_item_preview")
EXPEDIENT_FUNCTIONS = ("close_document_list_dialog", "open_document_with_system",
                       "show_document_preview", "show_expediente_documents_dialog")
SIZES = (0, 1, 2, 3, 4, 5, 8, 9)
PAGES = 3


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


def bind(path, names, scope):
    """Execute view closures at module level; free names resolve from scope."""
    found = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            found.setdefault(node.name, node)
    module = ast.Module(body=[found[name] for name in names], type_ignores=[])
    exec(compile(module, f"<{path.name}>", "exec"), scope)
    return scope


class MultidocBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.docs = []
        for index in range(9):
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
        self.page = SimpleNamespace(overlay=[], update=Mock())

    def tearDown(self):
        for path, content in self.originals.items():
            self.assertEqual(path.read_bytes(), content, path)

    def queue(self, size):
        return [{"path": str(path), "name": path.name} for path in self.docs[:size]]

    def open(self, size, index=0, **kwargs):
        queue = self.queue(size)
        path = queue[index]["path"] if queue else str(self.docs[0])
        kwargs.setdefault("near_window", 0)
        return open_document_viewer_modal(self.page, path, title=Path(path).name,
                                          queue=queue, queue_index=index, **kwargs)

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def labels(self, dialog):
        return [viewer_action_label(b) for b in viewer_action_buttons(dialog)]

    def compare(self, dialog):
        self.button(dialog, "Comparador 4").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.mode, multidoc.MODE_COMPARE)
        return layout

    def tile_names(self, dialog):
        return [view.tile.document.name for view in viewer_layout(dialog).tiles]

    def previews(self):
        return list((self.root / "previews").rglob("*.png"))

    def preview_dirs(self):
        base = self.root / "previews" / "v2"
        return [p for p in base.iterdir() if p.is_dir()] if base.exists() else []


class QueueModelTests(unittest.TestCase):
    def test_sizes_groups_and_bounds(self):
        expected_groups = {0: 0, 1: 1, 2: 1, 3: 1, 4: 1, 5: 2, 8: 2, 9: 3}
        for size in SIZES:
            with self.subTest(size=size):
                queue = multidoc.DocumentQueue([{"path": f"/tmp/d{i}.pdf"} for i in range(size)])
                self.assertEqual(len(queue), size)
                self.assertEqual(queue.group_count, expected_groups[size])
                self.assertFalse(queue.can_move(-1))
                self.assertFalse(queue.can_move_group(-1))
                if not size:
                    self.assertIsNone(queue.active)
                    self.assertEqual(queue.group(), ())
                    self.assertFalse(queue.move(1) or queue.move_group(1))
                    continue
                # Groups by position: [0..3], [4..7], [8].
                sizes = []
                while True:
                    group = queue.group()
                    self.assertEqual([d.index for d in group],
                                     list(range(queue.group_index * 4, queue.group_index * 4 + len(group))))
                    sizes.append(len(group))
                    if not queue.move_group(1):
                        break
                self.assertEqual(sum(sizes), size)
                self.assertTrue(all(s == 4 for s in sizes[:-1]))
                self.assertEqual(queue.group_label, f"Grupo {queue.group_count} de {queue.group_count}")
                self.assertFalse(queue.can_move_group(1))
                queue.select(size - 1)
                self.assertFalse(queue.can_move(1))
                self.assertEqual(queue.document_label, f"Documento {size} de {size}")
                queue.select(999)
                self.assertEqual(queue.active_index, size - 1)

    def test_incomplete_group_summary_and_stable_keys(self):
        queue = multidoc.DocumentQueue(
            [{"path": f"/tmp/d{i}.pdf", "name": f"D{i}"} for i in range(5)]
            + [{"path": "", "key": "inbox:77"}, {"path": ""}], 4)
        self.assertEqual(queue.group_summary, "3 documentos · Documentos 5–7 de 7")
        self.assertEqual(queue.documents[0].key, f"path:{Path('/tmp/d0.pdf')}")
        self.assertEqual(queue.documents[5].key, "inbox:77")
        self.assertEqual(queue.documents[6].key, "position:6")
        self.assertEqual(queue.documents[6].name, "Documento sin nombre")
        single = multidoc.DocumentQueue([{"path": "/tmp/x.pdf"}])
        self.assertEqual(single.group_summary, "1 documento · Documento 1 de 1")


class SessionReleaseTests(MultidocBase):
    def test_release_detaches_resources_and_keeps_session_usable(self):
        session = DocumentPreviewSession(near_window=1)
        session.render_window(PreviewRequest(str(self.docs[0]), None, 2, 1.0), session.invalidate())
        self.assertEqual(len(self.previews()), 3)
        resources = session.release()
        self.assertEqual(session.loaded_window, {})
        self.assertTrue(all(p.is_file() for p in self.previews()))  # disk-free
        resources.close()
        self.assertEqual(self.previews(), [])
        result = session.render_window(PreviewRequest(str(self.docs[1]), None, 1, 1.0),
                                       session.invalidate())
        self.assertTrue(result["ok"])
        session.close()
        self.assertIsNone(session.release())
        self.assertEqual(self.previews(), [])


class SingleModeQueueTests(MultidocBase):
    def test_queue_sizes_show_visible_document_arrows_apart_from_pages_and_zoom(self):
        for size in SIZES:
            with self.subTest(size=size):
                dialog = self.open(size)
                layout = viewer_layout(dialog)
                controls = dialog.content.content.controls
                if size <= 1:
                    # DV23 shell unchanged: no strip, no queue or mode commands.
                    self.assertEqual(len(controls), 2)
                    self.assertFalse({"Doc anterior", "Doc siguiente", "Comparador 4"}
                                     & set(self.labels(dialog)))
                    self.button(dialog, "Cerrar").on_click(None)
                    continue
                strip, info_row, canvas = controls
                previous, following = self.button(dialog, "Doc anterior"), self.button(dialog, "Doc siguiente")
                # Diagnosis: the arrows were only in the model and the cramped info
                # row. Now they are in the strip, never in the page/zoom toolbar.
                for command in (previous, following, layout.queue_label):
                    self.assertTrue(contains(strip, command))
                    self.assertFalse(contains(dialog.actions[0], command))
                    self.assertFalse(contains(info_row, command))
                self.assertFalse(contains(strip, layout.page_label))
                self.assertFalse(contains(strip, layout.zoom_label))
                self.assertGreaterEqual(previous.height, 36)
                self.assertEqual(layout.queue_label.value, f"Documento 1 de {size}")
                self.assertTrue(previous.disabled)
                self.assertEqual(previous.tooltip, "Es el primer documento de la cola.")
                for step in range(1, size):
                    self.button(dialog, "Doc siguiente").on_click(None)
                    self.assertEqual(viewer_layout(dialog).queue_label.value, f"Documento {step + 1} de {size}")
                last = self.button(dialog, "Doc siguiente")
                self.assertTrue(last.disabled)
                self.assertEqual(last.tooltip, "Es el último documento de la cola.")
                self.assertEqual(viewer_layout(dialog).title.value, f"doc{size - 1}.pdf")
                self.assertEqual(viewer_active_document(dialog).index, size - 1)
                self.assertFalse(self.button(dialog, "Doc anterior").disabled)
                # Canvas gives up exactly the strip's height; the shell keeps its size.
                self.assertEqual(canvas.height + multidoc.strip_height(layout.metrics) + 10,
                                 layout.metrics.canvas_height)
                self.button(dialog, "Cerrar").on_click(None)
                self.assertEqual(self.page.overlay, [])
        self.assertEqual(self.previews(), [])

    def test_queue_step_to_failing_document_stays_in_viewer(self):
        missing = self.root / "missing.pdf"
        queue = self.queue(1) + [{"path": str(missing), "name": "missing.pdf"}]
        error = Mock()
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], queue=queue, on_error=error)
        self.button(dialog, "Doc siguiente").on_click(None)
        error.assert_not_called()
        self.assertTrue(dialog.open)
        self.assertEqual(dialog.content.content.controls[-1].content.value, "El documento no existe.")
        self.assertEqual(viewer_layout(dialog).queue_label.value, "Documento 2 de 2")
        # Opening still reports to the caller, as in DV23.
        open_document_viewer_modal(self.page, str(missing), queue=list(reversed(queue)), on_error=error)
        error.assert_called_once()


class ComparatorTests(MultidocBase):
    def test_groups_of_four_render_one_page_per_document(self):
        dialog = self.open(9, near_window=3)
        with patch.object(service, "create_document_preview",
                          wraps=service.create_document_preview) as render:
            layout = self.compare(dialog)
        # Mosaic: one page per document, never the 7-page window per tile.
        self.assertEqual([(Path(c.args[0]).name, c.kwargs["page_number"]) for c in render.call_args_list],
                         [(f"doc{i}.pdf", 1) for i in range(4)])
        self.assertEqual(self.tile_names(dialog), [f"doc{i}.pdf" for i in range(4)])
        self.assertEqual(layout.group_label.value, "Grupo 1 de 3")
        self.assertTrue(self.button(dialog, "Grupo anterior").disabled)
        self.assertTrue(all(view.tile.ready for view in layout.tiles))
        self.assertEqual([view.page_label.value for view in layout.tiles], [f"Página 1 de {PAGES}"] * 4)
        # The single-mode window was released: only the four tile PNGs remain.
        self.assertEqual(len(self.previews()), 4)
        self.assertEqual(layout.comparator.live_sessions(), 4)
        self.button(dialog, "Grupo siguiente").on_click(None)
        self.assertEqual(self.tile_names(dialog), [f"doc{i}.pdf" for i in range(4, 8)])
        self.button(dialog, "Grupo siguiente").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(self.tile_names(dialog), ["doc8.pdf"])
        self.assertEqual(layout.group_label.value, "Grupo 3 de 3")
        self.assertEqual(layout.comparator.live_sessions(), 1)
        self.assertEqual(len(self.previews()), 1)
        last = self.button(dialog, "Grupo siguiente")
        self.assertTrue(last.disabled)
        self.assertEqual(last.tooltip, "Es el último grupo de la cola.")
        self.button(dialog, "Cerrar").on_click(None)

    def test_incomplete_groups_layout_and_empty_slots(self):
        for size, shape in ((2, (1, 2)), (3, (2, 2)), (4, (2, 2)), (5, (2, 2))):
            with self.subTest(size=size):
                dialog = self.open(size)
                layout = self.compare(dialog)
                grid = layout.canvas.content
                self.assertEqual((len(grid.controls), len(grid.controls[0].controls)), shape)
                empty = [t for t in walk(layout.canvas) if isinstance(t, ft.Text)
                         and t.value.startswith("Grupo incompleto")]
                self.assertEqual(len(empty), 1 if size == 3 else 0)
                self.assertEqual(len(layout.tiles), min(size, 4))
                if size == 5:
                    self.button(dialog, "Grupo siguiente").on_click(None)
                    layout = viewer_layout(dialog)
                    self.assertEqual(self.tile_names(dialog), ["doc4.pdf"])
                    self.assertEqual(layout.tiles[0].container.width, layout.metrics.content_width)
                    self.assertEqual(layout.queue.group_summary, "1 documento · Documento 5 de 5")
                self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.previews(), [])

    def test_active_selection_is_unambiguous_and_survives_mode_changes(self):
        dialog = self.open(6, index=5)
        layout = self.compare(dialog)
        self.assertEqual(layout.group_label.value, "Grupo 2 de 2")
        self.assertEqual([v.active for v in layout.tiles], [False, True])
        active = layout.tiles[1].container
        self.assertEqual((active.border.top.width, active.border.top.color), (2, "#0057B8"))
        self.assertEqual(layout.tiles[0].container.border.top.width, 1)
        self.assertEqual(viewer_active_document(dialog).index, 5)
        keys = [d.key for d in layout.queue.documents]
        # Selecting a tile changes header, info row and commands, nothing else.
        layout.tiles[0].container.on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual([v.active for v in layout.tiles], [True, False])
        self.assertEqual(layout.title.value, "doc4.pdf")
        self.assertEqual(layout.path.value, str(self.docs[4]))
        self.assertEqual(layout.queue_label.value, "Activo: Documento 5 de 6")
        layout.tiles[0].next_page.on_click(None)
        self.assertEqual(viewer_layout(dialog).tiles[0].page_label.value, f"Página 2 de {PAGES}")
        # Back to single mode: same document, same page, same queue order.
        self.button(dialog, "Documento único").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.mode, multidoc.MODE_SINGLE)
        self.assertEqual(layout.title.value, "doc4.pdf")
        self.assertEqual(layout.page_label.value, f"Página 2 de {PAGES}")
        self.assertEqual(layout.queue_label.value, "Documento 5 de 6")
        self.assertEqual([d.key for d in layout.queue.documents], keys)
        self.assertEqual(layout.comparator.live_sessions(), 0)
        # And again: the mosaic reopens on the active document's group and page.
        layout = self.compare(dialog)
        self.assertEqual(self.tile_names(dialog), ["doc4.pdf", "doc5.pdf"])
        self.assertTrue(layout.tiles[0].active)
        self.assertEqual(layout.tiles[0].page_label.value, f"Página 2 de {PAGES}")
        self.button(dialog, "Cerrar").on_click(None)

    def test_page_and_zoom_are_independent_per_tile(self):
        dialog = self.open(4)
        layout = self.compare(dialog)
        layout.tiles[1].zoom_in.on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual([v.zoom_label.value for v in layout.tiles], ["1.0x", "1.4x", "1.0x", "1.0x"])
        self.assertTrue(layout.tiles[1].active)  # acting on a tile activates it
        self.assertEqual(layout.zoom_label.value, "Zoom: 1.4x")
        layout.tiles[0].next_page.on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual([v.page_label.value for v in layout.tiles][:2],
                         [f"Página 2 de {PAGES}", f"Página 1 de {PAGES}"])
        # Toolbar commands follow the active tile only.
        self.button(dialog, "Siguiente").on_click(None)
        self.button(dialog, "Zoom +").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.tiles[0].page_label.value, f"Página 3 de {PAGES}")
        self.assertEqual([v.zoom_label.value for v in layout.tiles], ["1.4x", "1.4x", "1.0x", "1.0x"])
        self.assertTrue(self.button(dialog, "Siguiente").disabled)
        self.assertEqual(self.button(dialog, "Siguiente").tooltip, "Ya estás en la última página.")
        self.assertTrue(layout.tiles[0].next_page.disabled)
        self.assertFalse(layout.tiles[1].next_page.disabled)
        self.button(dialog, "Cerrar").on_click(None)

    def test_stale_callbacks_after_group_and_mode_changes_are_inert(self):
        dialog = self.open(9, near_window=1)
        single_view = dialog.content.content.controls[-1].content
        layout = self.compare(dialog)
        stale_tile = layout.tiles[0]
        self.button(dialog, "Grupo siguiente").on_click(None)
        current = viewer_layout(dialog)
        with patch.object(service, "create_document_preview") as render:
            single_view.on_scroll(SimpleNamespace(pixels=2 * 1048))
            stale_tile.next_page.on_click(None)
            stale_tile.zoom_in.on_click(None)
            stale_tile.container.on_click(None)
            render.assert_not_called()
        self.assertEqual(viewer_layout(dialog).queue.active_index, 4)
        self.assertEqual(self.tile_names(dialog), [f"doc{i}.pdf" for i in range(4, 8)])
        self.assertFalse(stale_tile.tile.live)
        self.assertIs(viewer_layout(dialog).comparator, current.comparator)
        self.button(dialog, "Cerrar").on_click(None)

    def test_rapid_group_change_during_render_drops_the_abandoned_group(self):
        dialog = self.open(9)
        actual = service.create_document_preview
        fired = []

        def racing(path, **kwargs):
            if not fired:
                fired.append(path)
                # A second click arrives while the first group is still rendering.
                self.button(dialog, "Grupo siguiente").on_click(None)
            return actual(path, **kwargs)

        with patch.object(service, "create_document_preview", side_effect=racing):
            layout = self.compare(dialog)
        layout = viewer_layout(dialog)
        self.assertEqual(self.tile_names(dialog), [f"doc{i}.pdf" for i in range(4, 8)])
        self.assertTrue(all(view.tile.ready for view in layout.tiles))
        self.assertEqual(layout.comparator.live_sessions(), 4)
        self.assertEqual(len(self.previews()), 4)
        # Quick toggles never leave more than four sessions alive.
        for label in ("Grupo siguiente", "Grupo anterior", "Grupo anterior", "Documento único"):
            self.button(dialog, label).on_click(None)
            self.assertLessEqual(viewer_layout(dialog).comparator.live_sessions(), 4)
        layout = viewer_layout(dialog)
        self.assertEqual(layout.mode, multidoc.MODE_SINGLE)
        self.assertEqual(layout.title.value, "doc0.pdf")
        self.assertEqual(layout.comparator.live_sessions(), 0)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.previews(), [])
        self.assertEqual(self.preview_dirs(), [])

    def test_failure_stays_inside_its_tile(self):
        bad = self.root / "bad.pdf"
        bad.write_bytes(b"not a PDF")
        text = self.root / "notes.txt"
        text.write_text("text")
        queue = [{"path": str(self.docs[0]), "name": "ok.pdf"},
                 {"path": str(self.root / "missing.pdf"), "name": "missing.pdf"},
                 {"path": str(bad), "name": "bad.pdf"},
                 {"path": str(text), "name": "notes.txt"},
                 {"path": "", "name": "sin ruta"}]
        toolbar = Mock(return_value=[])
        dialog = open_document_viewer_modal(self.page, queue[0]["path"], queue=queue,
                                            toolbar_actions=toolbar)
        layout = self.compare(dialog)
        statuses = [(v.tile.status, v.tile.message) for v in layout.tiles]
        self.assertEqual(statuses[0], (multidoc.READY, ""))
        self.assertEqual(statuses[1], (multidoc.FAILED, "El documento no existe."))
        self.assertEqual(statuses[2][0], multidoc.FAILED)
        self.assertIn("No se pudo generar", statuses[2][1])
        self.assertEqual(statuses[3], (multidoc.FAILED,
                                       "Este tipo de documento no tiene preview integrada todavía."))
        for view in layout.tiles[1:]:
            self.assertIn(view.tile.message,
                          [t.value for t in walk(view.body) if isinstance(t, ft.Text)])
            self.assertTrue(contains(view.container, view.name))
        # A failed active document offers no PDF tools and explains its commands.
        toolbar.reset_mock()
        layout.tiles[1].container.on_click(None)
        toolbar.assert_not_called()
        self.assertTrue(self.button(dialog, "Zoom +").disabled)
        self.assertEqual(self.button(dialog, "Zoom +").tooltip, "El documento activo no tiene vista previa.")
        self.assertTrue(all(b.disabled for b in viewer_layout(dialog).tiles[1].buttons))
        self.button(dialog, "Grupo siguiente").on_click(None)
        layout = viewer_layout(dialog)
        self.assertEqual((layout.tiles[0].tile.status, layout.tiles[0].tile.message),
                         (multidoc.FAILED, multidoc.NO_PATH))
        self.assertTrue(self.button(dialog, "Abrir con visor del sistema").disabled)
        self.button(dialog, "Cerrar").on_click(None)

    def test_expediente_scope_applies_to_every_tile(self):
        outside = self.root / "outside"
        outside.mkdir()
        foreign = outside / "foreign.pdf"
        foreign.write_bytes(self.originals[self.docs[0]])
        inside = self.root / "exp"
        inside.mkdir()
        own = inside / "own.pdf"
        own.write_bytes(self.originals[self.docs[1]])
        queue = [{"path": str(own), "name": "own.pdf"}, {"path": str(foreign), "name": "foreign.pdf"}]
        with patch.object(service, "get_expediente_document_root",
                          return_value={"exists": True, "root_path": str(inside)}):
            dialog = open_document_viewer_modal(self.page, str(own), expediente_id=42, queue=queue)
            layout = self.compare(dialog)
        self.assertTrue(layout.tiles[0].tile.ready)
        self.assertEqual(layout.tiles[1].tile.message,
                         "El archivo no pertenece a la carpeta documental del expediente.")
        self.button(dialog, "Cerrar").on_click(None)

    def test_close_and_dismiss_release_every_session_and_png(self):
        for close in ("button", "dismiss"):
            with self.subTest(close=close):
                dialog = self.open(5, near_window=1)
                layout = self.compare(dialog)
                stale = layout.tiles[2]
                self.assertEqual(len(self.previews()), 4)
                if close == "button":
                    self.button(dialog, "Cerrar").on_click(None)
                else:
                    dialog.on_dismiss(None)
                self.assertFalse(dialog.open)
                self.assertIsNone(dialog.content)
                self.assertEqual(self.page.overlay, [])
                self.assertEqual(layout.comparator.live_sessions(), 0)
                self.assertEqual(self.previews(), [])
                self.assertEqual(self.preview_dirs(), [])
                with patch.object(service, "create_document_preview") as render:
                    stale.next_page.on_click(None)
                    stale.container.on_click(None)
                    render.assert_not_called()
                self.assertIsNone(dialog.content)

    def test_close_during_tile_render_is_immediate_and_discards_the_result(self):
        dialog = self.open(4)
        layout = self.compare(dialog)
        actual = service.create_document_preview
        entered, release = threading.Event(), threading.Event()

        def blocking(path, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return actual(path, **kwargs)

        with patch.object(service, "create_document_preview", side_effect=blocking), \
                ThreadPoolExecutor(2) as pool:
            rendering = pool.submit(layout.tiles[2].next_page.on_click, None)
            try:
                self.assertTrue(entered.wait(5))
                started = time.perf_counter()
                pool.submit(self.button(dialog, "Cerrar").on_click, None).result(5)
                self.assertLess(time.perf_counter() - started, 1.0)
                self.assertFalse(rendering.done())
            finally:
                release.set()
            rendering.result(5)
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.content)
        self.assertEqual(self.previews(), [])


class ActiveDocumentPdfToolsTests(MultidocBase):
    def setUp(self):
        super().setUp()
        self.items = {str(path): {"id": 100 + index, "stored_path": str(path)}
                      for index, path in enumerate(self.docs)}
        self.handlers = {"rotate": Mock(), "split": Mock()}
        self.adapter = PdfToolsToolbarAdapter(lambda request: self.items.get(request.path),
                                              self.handlers, Mock())

    def test_tools_appear_once_and_target_only_the_active_document(self):
        dialog = self.open(4, toolbar_actions=self.adapter)
        layout = self.compare(dialog)
        operations = {operation for operation, _ in PDF_ACTIONS}
        toolbar_tools = [c for c in walk(dialog.actions[0]) if getattr(c, "data", None) in operations]
        self.assertEqual(len(toolbar_tools), len(PDF_ACTIONS))
        self.assertFalse([c for c in walk(layout.canvas) if getattr(c, "data", None) in operations])
        self.assertEqual(self.labels(dialog).count("Rotar páginas"), 1)
        stale_rotate = self.button(dialog, "Rotar páginas")
        stale_rotate.on_click("first")
        self.handlers["rotate"].assert_called_once_with("first", item_id=100)
        viewer_layout(dialog).tiles[2].container.on_click(None)
        stale_rotate.on_click("stale")
        self.handlers["rotate"].assert_called_once()
        self.button(dialog, "Rotar páginas").on_click("active")
        self.assertEqual(self.handlers["rotate"].call_args.args, ("active",))
        self.assertEqual(self.handlers["rotate"].call_args.kwargs, {"item_id": 102})
        self.assertEqual(viewer_active_document(dialog).path, str(self.docs[2]))
        self.button(dialog, "Cerrar").on_click(None)

    def test_dv23_contract_without_queue_is_unchanged(self):
        parameters = list(inspect.signature(open_document_viewer_modal).parameters)
        self.assertEqual(parameters, ["page", "file_path", "title", "expediente_id", "initial_page",
                                      "initial_zoom", "queue", "queue_index", "dialog", "on_error",
                                      "toolbar_actions", "near_window"])
        toolbar = Mock(wraps=self.adapter)
        dialog = open_document_viewer_modal(self.page, str(self.docs[0]), toolbar_actions=toolbar,
                                            near_window=1)
        self.assertEqual(len(dialog.content.content.controls), 2)
        self.assertEqual(self.labels(dialog), [label for _, label in PDF_ACTIONS] + [
            "Anterior", "Siguiente", "Zoom -", "Zoom +", "Abrir con visor del sistema", "Cerrar"])
        self.assertEqual(toolbar.call_args.args[0], PreviewRequest(str(self.docs[0]), None, 1, 1.6))
        self.assertEqual(viewer_active_document(dialog).path, str(self.docs[0]))
        self.button(dialog, "Siguiente").on_click(None)
        self.button(dialog, "Rotar páginas").on_click("evt")
        self.handlers["rotate"].assert_called_once_with("evt", item_id=100)
        self.assertEqual(viewer_layout(dialog).page_label.value, f"Página 2 de {PAGES}")
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.previews(), [])


class ViewQueueWiringTests(MultidocBase):
    def bind_inbox(self, canonical=open_document_viewer_modal):
        self.inbox = {index + 1: {"id": index + 1, "stored_path": str(path),
                                  "original_filename": f"Bandeja {index + 1}.pdf"}
                      for index, path in enumerate(self.docs[:3])}
        self.state = {"selected_item_id": 2, "selected_item_ids": set(),
                      "items": [dict(item) for item in self.inbox.values()]}
        self.inbox_error = Mock()
        patcher = patch.object(inbox_tools, "get_inbox_item",
                               side_effect=lambda item_id: self.inbox.get(int(item_id)))
        patcher.start()
        self.addCleanup(patcher.stop)
        return bind(INBOX, INBOX_FUNCTIONS, dict(
            page=self.page, state=self.state, open_document_viewer_modal=canonical,
            ViewerPdfTools=ViewerPdfTools,
            document_inbox_service=SimpleNamespace(get_inbox_item=lambda i: self.inbox.get(int(i))),
            refresh_items=Mock(), _document_tool_register_response_in_batch_if_needed=Mock(),
            show_error=self.inbox_error, batch_detail_message=SimpleNamespace(content=None, update=Mock()),
            error_alert=lambda text: ft.Text(str(text)), item=self.inbox[3],
        ))

    def test_inbox_queue_follows_listing_order_and_selection(self):
        canonical = Mock()
        scope = self.bind_inbox(canonical)
        scope["show_preview"]()
        kwargs = canonical.call_args.kwargs
        self.assertEqual([e["inbox_item_id"] for e in kwargs["queue"]], [1, 2, 3])
        self.assertEqual([e["key"] for e in kwargs["queue"]], ["inbox:1", "inbox:2", "inbox:3"])
        self.assertEqual(kwargs["queue_index"], 1)
        self.assertEqual(kwargs["file_path"], str(self.docs[1]))
        # The toolbar resolves the active document's own item, by its path.
        toolbar = kwargs["toolbar_actions"]
        self.assertEqual(toolbar.resolve_item(PreviewRequest(str(self.docs[2]), None, 1, 1.0))["id"], 3)
        # A multi-selection that includes the item becomes the queue, in listing order.
        self.state.update(selected_item_id=3, selected_item_ids={3, 1})
        scope["show_preview"]()
        self.assertEqual([e["inbox_item_id"] for e in canonical.call_args.kwargs["queue"]], [1, 3])
        self.assertEqual(canonical.call_args.kwargs["queue_index"], 1)
        self.state.update(selected_item_id=2)
        scope["show_preview"]()
        self.assertEqual(len(canonical.call_args.kwargs["queue"]), 3)
        # The isolated detail dialog keeps its own item and the full listing,
        # even while the main listing's checkboxes ({1, 3}) include that item.
        scope["detail_show_preview"]()
        kwargs = canonical.call_args.kwargs
        self.assertEqual([e["inbox_item_id"] for e in kwargs["queue"]], [1, 2, 3])
        self.assertEqual(kwargs["queue_index"], 2)
        self.assertEqual(kwargs["file_path"], str(self.docs[2]))
        self.assertEqual(self.state["selected_item_ids"], {1, 3})
        # Group documents: the batch list, with the linked-document fallback.
        batch = [{"id": 7, "stored_path": "", "linked_document_path": str(self.docs[4])},
                 {"id": 8, "stored_path": str(self.docs[5]), "original_filename": "ocho.pdf"}]
        scope["show_batch_item_preview"](batch[1], batch)
        kwargs = canonical.call_args.kwargs
        self.assertEqual([e["path"] for e in kwargs["queue"]], [str(self.docs[4]), str(self.docs[5])])
        self.assertEqual(kwargs["queue_index"], 1)
        # Without a listing (or a single item) the DV23 call is unchanged.
        scope["show_batch_item_preview"](batch[1])
        self.assertIsNone(canonical.call_args.kwargs["queue"])
        self.inbox_error.assert_not_called()

    def test_inbox_comparator_opens_tool_forms_for_the_active_item(self):
        scope = self.bind_inbox()
        scope["show_preview"]()
        dialog = self.page.overlay[-1]
        layout = self.compare(dialog)
        self.assertEqual(self.tile_names(dialog), ["Bandeja 1.pdf", "Bandeja 2.pdf", "Bandeja 3.pdf"])
        self.assertEqual(viewer_active_document(dialog).key, "inbox:2")
        layout.tiles[2].container.on_click(None)
        self.button(dialog, "Rotar páginas").on_click(None)
        form = self.page.overlay[-1].data
        self.assertIsInstance(form, PdfToolForm)
        self.assertEqual((form.operation, form.scope.inbox_item_id), ("rotate", 3))
        form.close()  # never submitted: no PDF operation runs
        self.assertIs(self.page.overlay[-1], dialog)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(self.state["selected_item_id"], 2)
        self.inbox_error.assert_not_called()

    def test_expedients_listing_cards_open_the_listing_as_queue(self):
        state = {"dialog_expediente_id": 42}
        cards = []
        list_dialog, viewer_dialog = ft.AlertDialog(modal=True), ft.AlertDialog(modal=True)
        self.page.overlay.extend([list_dialog, viewer_dialog])
        documents = SimpleNamespace(open_document=Mock(), list_expediente_documents=Mock(return_value={
            "root_path": str(self.root), "total_documents": 3,
            "documents": [{"path": str(p), "name": p.name, "previewable": True, "type": "pdf"}
                          for p in self.docs[:3]],
        }))

        def card(**kwargs):
            cards.append(kwargs)
            return ft.Container()

        canonical = Mock()
        scope = bind(EXPEDIENTS, EXPEDIENT_FUNCTIONS, dict(
            ft=ft, page=self.page, state=state, show_form_error=Mock(),
            document_viewer_service=documents, document_file_card=card,
            secondary_button=secondary_button, Q_PRIMARY_DARK="#003B7A", Q_MUTED="#64748B",
            document_list_dialog=list_dialog, document_viewer_dialog=viewer_dialog,
            open_document_viewer_modal=canonical,
        ))
        scope["show_expediente_documents_dialog"]()
        cards[2]["on_preview"](None)
        canonical.assert_called_once_with(
            self.page, str(self.docs[2]), title="doc2.pdf", expediente_id=42, initial_page=1,
            initial_zoom=1.6, queue=self.queue(3), queue_index=2, dialog=viewer_dialog,
            on_error=ANY, toolbar_actions=ANY)

    def test_every_expedients_preview_entry_passes_its_listing_queue(self):
        calls = [n for n in ast.walk(ast.parse(EXPEDIENTS.read_text(encoding="utf-8")))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "show_document_preview"]
        self.assertEqual(len(calls), 5)
        for call in calls:
            keywords = {k.arg for k in call.keywords}
            self.assertTrue(len(call.args) >= 6 or "queue" in keywords, ast.unparse(call))
        # The Bandeja queue reuses the listing it is given: no new data retrieval.
        tree = ast.parse(INBOX.read_text(encoding="utf-8"))
        options = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "inbox_viewer_options")
        called = {ast.unparse(n.func) for n in ast.walk(options) if isinstance(n, ast.Call)}
        self.assertFalse({c for c in called if c.startswith("document_inbox_service.")})
        self.assertNotIn("SELECT", ast.unparse(options).upper())


if __name__ == "__main__":
    unittest.main()
