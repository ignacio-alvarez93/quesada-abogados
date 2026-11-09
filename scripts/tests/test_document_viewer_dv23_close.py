"""DV23 close lifecycle: visual close first, cleanup after, never blocked by render.

Synthetic 25-page PDFs in temporary directories only. Latency bounds are
generous environmental guards; the measured p50/p95 are printed for evidence.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import statistics
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label, viewer_layout,
)


SLOT = 1648  # int(1000 * 1.6) + 48
CLOSE_BUDGET_MS = 300


class ModernPage:
    """Flet show_dialog/pop_dialog stack; pop does not dismiss by itself."""

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


class MountedDialog(ft.AlertDialog):
    """A dialog Flet has mounted: update() patches only its subtree."""

    def update(self):
        self.subtree_updates = getattr(self, "subtree_updates", 0) + 1


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


class Dv23CloseTests(unittest.TestCase):
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
        self.page = SimpleNamespace(overlay=[], update=Mock())

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)

    def open(self, page=None, **kwargs):
        return open_document_viewer_modal(page or self.page, str(self.source), **kwargs)

    def button(self, dialog, label):
        return next(b for b in viewer_action_buttons(dialog) if viewer_action_label(b) == label)

    def previews(self):
        return list((self.root / "previews").rglob("*.png"))

    def preview_dirs(self):
        base = self.root / "previews" / "v2"
        return [p for p in base.iterdir() if p.is_dir()] if base.exists() else []

    # -- ordering: visual close before disk work --------------------------------

    def test_dismiss_is_flushed_before_preview_files_are_deleted(self):
        """Regression: cleanup used to delete PNGs before the dismiss update."""
        page = ModernPage()
        dialog = self.open(page=page, initial_page=4)
        session = dialog.data
        events = []
        page.update.side_effect = lambda: events.append(("update", dialog.open, dialog.content))
        real_close = service.PreviewResources.close

        def observed(resources):
            lock_free = threading.Thread(target=lambda: events.append(
                ("lock", session._condition.acquire(timeout=1) and session._condition.release() is None)))
            lock_free.start()
            lock_free.join()
            events.append(("release", dialog.open, len(self.previews())))
            real_close(resources)

        with patch.object(service.PreviewResources, "close", observed):
            self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(events[0], ("update", False, None))
        self.assertEqual(events[1], ("lock", True))  # no publication lock during disk work
        self.assertEqual(events[2][:2], ("release", False))
        self.assertGreater(events[2][2], 0)
        self.assertEqual(self.previews(), [])
        self.assertEqual(page.popped, 1)

    def test_cancel_is_disk_free_and_close_releases_once(self):
        session = DocumentPreviewSession(near_window=1)
        session.render_window(PreviewRequest(str(self.source), None, 3, 1.6), session.invalidate())
        files = self.previews()
        self.assertEqual(len(files), 3)
        resources = session.cancel()
        self.assertTrue(all(path.is_file() for path in files))
        self.assertFalse(session.is_current(session.generation))
        self.assertIsNone(session.cancel())
        session.close()  # already cancelled: nothing left to release
        self.assertTrue(all(path.is_file() for path in files))
        resources.close()
        self.assertEqual(self.previews(), [])
        self.assertEqual(self.preview_dirs(), [])

    def test_mounted_dialog_close_patches_only_the_dialog_subtree(self):
        """Regression: close used to diff the whole CRM page with page.update()."""
        page = ModernPage()
        dialog = self.open(page=page, dialog=MountedDialog(modal=True), initial_page=4)
        opened_page_updates = page.update.call_count
        subtree = getattr(dialog, "subtree_updates", 0)
        self.button(dialog, "Siguiente").on_click(None)
        self.assertEqual(dialog.subtree_updates, subtree + 1)
        self.button(dialog, "Cerrar").on_click(None)
        self.assertEqual(page.update.call_count, opened_page_updates)
        self.assertEqual(dialog.subtree_updates, subtree + 2)
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.content)
        self.assertEqual(self.previews(), [])

    def test_release_failure_never_reopens_or_breaks_close(self):
        dialog = self.open()
        with patch.object(service.PreviewResources, "close", side_effect=PermissionError("locked")):
            self.button(dialog, "Cerrar").on_click(None)
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.content)
        self.assertEqual(self.page.overlay, [])
        self.assertFalse(dialog.data.is_current(dialog.data.generation))

    # -- races against render and scroll -----------------------------------------

    def test_close_during_native_render_returns_immediately_and_discards_result(self):
        dialog = self.open(near_window=1)
        view = viewer_layout(dialog).canvas.content
        close = self.button(dialog, "Cerrar")
        actual = service.create_document_preview
        entered, release = threading.Event(), threading.Event()

        def blocking(path, **kwargs):
            if kwargs["page_number"] == 20:
                entered.set()
                self.assertTrue(release.wait(5))
            return actual(path, **kwargs)

        with patch.object(service, "create_document_preview", side_effect=blocking), \
                ThreadPoolExecutor(2) as pool:
            scrolling = pool.submit(view.on_scroll, SimpleNamespace(pixels=19 * SLOT))
            try:
                self.assertTrue(entered.wait(5))
                started = time.perf_counter()
                pool.submit(close.on_click, None).result(5)
                elapsed = (time.perf_counter() - started) * 1000
                self.assertFalse(scrolling.done())
            finally:
                release.set()
            scrolling.result(5)
        self.assertLess(elapsed, CLOSE_BUDGET_MS)
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.content)
        self.assertEqual(self.page.overlay, [])
        self.assertEqual(self.previews(), [])
        self.assertEqual(self.preview_dirs(), [])

    def test_close_waits_at_most_for_one_inflight_publication(self):
        dialog = self.open(near_window=0)
        view = viewer_layout(dialog).canvas.content
        publishing, proceed = threading.Event(), threading.Event()

        def slow_update():
            if not publishing.is_set():
                publishing.set()
                self.assertTrue(proceed.wait(5))
        self.page.update.side_effect = slow_update
        with ThreadPoolExecutor(2) as pool:
            scrolling = pool.submit(view.on_scroll, SimpleNamespace(pixels=9 * SLOT))
            self.assertTrue(publishing.wait(5))
            closing = pool.submit(self.button(dialog, "Cerrar").on_click, None)
            time.sleep(0.05)
            self.assertFalse(closing.done())  # serialized behind the in-flight flush
            proceed.set()
            closing.result(5)
            scrolling.result(5)
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.content)
        # The scroll drain loop saw the close and published nothing more.
        self.assertEqual(self.page.update.call_count, 3)  # open, scroll publish, close

    def test_stale_callbacks_are_inert_after_close(self):
        tasks = []
        page = SimpleNamespace(overlay=[], update=Mock(), run_task=tasks.append)
        dialog = self.open(page=page, initial_page=4)
        view = viewer_layout(dialog).canvas.content
        header_close = next(c for c in dialog.title.content.controls if isinstance(c, ft.IconButton))
        stale = [self.button(dialog, label) for label in ("Siguiente", "Zoom +", "Cerrar")]
        self.button(dialog, "Cerrar").on_click(None)
        updates = page.update.call_count
        with patch.object(service, "create_document_preview") as render, \
                patch.object(ft.ListView, "scroll_to") as scroll_to:
            for command in stale:
                command.on_click(None)
            header_close.on_click(None)
            view.on_scroll(SimpleNamespace(pixels=10 * SLOT))
            for task in tasks:
                asyncio.run(task())
            render.assert_not_called()
            scroll_to.assert_not_called()
        self.assertEqual(page.update.call_count, updates)
        self.assertIsNone(dialog.content)

    # -- reuse, overlays, repetition and latency ---------------------------------

    def test_reused_caller_dialog_closes_previous_session_without_ghosts(self):
        view_dialog = ft.AlertDialog(modal=True)
        self.page.overlay.append(view_dialog)
        self.open(dialog=view_dialog, initial_page=2)
        first, old_close = view_dialog.data, self.button(view_dialog, "Cerrar")
        self.open(dialog=view_dialog, initial_page=5)
        self.assertFalse(first.is_current(first.generation))
        old_close.on_click(None)
        self.assertTrue(view_dialog.open)
        self.assertEqual(viewer_layout(view_dialog).page_label.value, "Página 5 de 25")
        self.button(view_dialog, "Cerrar").on_click(None)
        self.assertFalse(view_dialog.open)
        self.assertEqual(self.page.overlay, [view_dialog])  # caller-owned, kept
        self.assertEqual(self.previews(), [])

    def test_repeated_open_close_has_no_leaks_and_meets_latency_budget(self):
        page = ModernPage()
        visual, handler = [], []
        for _ in range(30):
            dialog = self.open(page=page, initial_page=4)
            close = self.button(dialog, "Cerrar")
            marks = {}
            page.update.side_effect = lambda: marks.setdefault("flush", time.perf_counter())
            started = time.perf_counter()
            close.on_click(None)
            finished = time.perf_counter()
            visual.append((marks["flush"] - started) * 1000)
            handler.append((finished - started) * 1000)
            page.update.side_effect = None
            dialog.on_dismiss(SimpleNamespace(control=dialog, data=None))
            self.assertFalse(dialog.open)
            self.assertEqual(page._dialogs.controls, [])
            self.assertEqual(page.overlay, [])
            self.assertEqual(self.previews(), [])
            self.assertEqual(self.preview_dirs(), [])
        report = (f"DV23 close latency (25-page synthetic PDF, n=30): "
                  f"visual p50={statistics.median(visual):.2f}ms p95={percentile(visual, .95):.2f}ms; "
                  f"handler incl. cleanup p50={statistics.median(handler):.2f}ms "
                  f"p95={percentile(handler, .95):.2f}ms")
        print("\n" + report)
        self.assertLess(percentile(visual, .95), CLOSE_BUDGET_MS, report)
        self.assertLess(percentile(handler, .95), CLOSE_BUDGET_MS, report)
        self.assertEqual(page.popped, 30)


if __name__ == "__main__":
    unittest.main()
