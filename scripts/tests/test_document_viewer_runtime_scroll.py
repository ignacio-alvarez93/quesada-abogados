"""Runtime lifecycle and scroll regressions with synthetic, temporary PDFs only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from frontend.components.document_viewer_modal import (
    open_document_viewer_modal, viewer_action_buttons, viewer_action_label, viewer_layout,
)


SLOT = 1648  # int(1000 * 1.6) + 48


class ModernPage:
    """Mimics Flet's show_dialog/pop_dialog stack and its on_dismiss wrapper."""

    def __init__(self):
        self.overlay = []
        self._dialogs = SimpleNamespace(controls=[])
        self.update = Mock()
        self.shown = 0
        self.popped = 0

    def show_dialog(self, dialog):
        if any(item is dialog for item in self._dialogs.controls):
            raise RuntimeError('Dialog is already opened')
        self.shown += 1
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
        if not self._dialogs.controls:
            raise RuntimeError('No dialog to pop')
        self.popped += 1
        dialog = self._dialogs.controls[-1]
        dialog.open = False
        return dialog

    def client_dismiss(self, dialog):
        # Flutter reports the dismissal after the dialog has closed.
        dialog.on_dismiss(SimpleNamespace(control=dialog))


def fake_preview(root, total=10):
    def preview(path, **kwargs):
        number = kwargs['page_number']
        return dict(ok=True, preview_type='pdf', preview_path=str(root / f'missing-{number}.png'),
                    page_number=number, total_pages=total, zoom=kwargs['zoom'])
    return preview


class RuntimeScrollTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as document:
            for index in range(8):
                document.new_page(width=150, height=150).insert_text((20, 30), f'Page {index + 1}')
            document.save(self.source)
        self.original = self.source.read_bytes()
        patcher = patch.object(service, 'PREVIEW_DIR', self.root / 'previews')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.page = SimpleNamespace(overlay=[], update=Mock())

    def open(self, page=None, **kwargs):
        return open_document_viewer_modal(page or self.page, str(self.source), **kwargs)

    def button(self, dialog, label):
        return next(action for action in viewer_action_buttons(dialog) if viewer_action_label(action) == label)

    def labels(self, dialog):
        return [viewer_action_label(a) for a in viewer_action_buttons(dialog)]

    def list_view(self, dialog):
        return dialog.content.content.controls[-1].content

    def scroll(self, dialog_or_view, page_number):
        view = dialog_or_view if isinstance(dialog_or_view, ft.ListView) else self.list_view(dialog_or_view)
        view.on_scroll(SimpleNamespace(pixels=(page_number - 1) * SLOT))

    def previews(self):
        return list((self.root / 'previews').rglob('*.png'))

    def test_repeated_open_close_and_dismiss_leave_no_ghost_overlay(self):
        for _ in range(5):
            dialog = self.open(near_window=1)
            self.assertIn(dialog, self.page.overlay)
            close = self.button(dialog, 'Cerrar')
            close.on_click(None)
            close.on_click(None)
            dialog.on_dismiss(None)
            self.assertFalse(dialog.open)
            self.assertIsNone(dialog.content)
            self.assertEqual(self.page.overlay, [])
            self.assertEqual(self.previews(), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_modern_api_shows_once_and_pops_once(self):
        page = ModernPage()
        for round_number in range(1, 4):
            dialog = self.open(page=page)
            self.assertEqual(page.shown, round_number)
            self.button(dialog, 'Siguiente').on_click(None)
            self.scroll(dialog, 5)
            self.assertEqual(page.shown, round_number)
            self.button(dialog, 'Cerrar').on_click(None)
            self.assertEqual(page.popped, round_number)
            page.client_dismiss(dialog)
            self.assertEqual(page.popped, round_number)
            self.assertEqual(page._dialogs.controls, [])
            self.assertEqual(page.overlay, [])
            self.assertFalse(dialog.open)

    def test_close_never_pops_a_dialog_stacked_above_the_viewer(self):
        page = ModernPage()
        dialog = self.open(page=page)
        tool_dialog = ft.AlertDialog(modal=True)
        page.show_dialog(tool_dialog)
        self.button(dialog, 'Cerrar').on_click(None)
        self.assertEqual(page.popped, 0)
        self.assertFalse(dialog.open)
        self.assertTrue(tool_dialog.open)
        page.client_dismiss(dialog)
        self.assertEqual(page._dialogs.controls, [tool_dialog])

    def test_external_dismiss_closes_session_and_preserves_view_dialog(self):
        view_dialog = ft.AlertDialog(modal=True)
        view_dismiss = Mock()
        view_dialog.on_dismiss = view_dismiss
        self.page.overlay.append(view_dialog)
        for count in (1, 2):
            self.open(dialog=view_dialog)
            session = view_dialog.data
            close = self.button(view_dialog, 'Cerrar')
            event = SimpleNamespace(control=view_dialog)
            view_dialog.on_dismiss(event)
            self.assertFalse(session.is_current(session.generation))
            self.assertIsNone(session.current_request)
            self.assertFalse(view_dialog.open)
            self.assertIn(view_dialog, self.page.overlay)
            # The view handler runs once per dismissal, never chained twice.
            self.assertEqual(view_dismiss.call_count, count)
            view_dismiss.assert_called_with(event)
            updates = self.page.update.call_count
            close.on_click(None)
            self.assertEqual(self.page.update.call_count, updates)

    def test_close_is_not_blocked_by_render_in_progress(self):
        dialog = self.open(near_window=0)
        view = self.list_view(dialog)
        close = self.button(dialog, 'Cerrar')
        actual = service.create_document_preview
        entered, release = threading.Event(), threading.Event()

        def blocking(path, **kwargs):
            if kwargs['page_number'] == 5:
                entered.set()
                self.assertTrue(release.wait(5))
            return actual(path, **kwargs)

        with patch.object(service, 'create_document_preview', side_effect=blocking), \
                ThreadPoolExecutor(2) as pool:
            scrolling = pool.submit(self.scroll, view, 5)
            try:
                self.assertTrue(entered.wait(5))
                pool.submit(close.on_click, None).result(5)
                self.assertFalse(scrolling.done())
            finally:
                release.set()
            scrolling.result(5)
        self.assertIsNone(dialog.content)
        self.assertFalse(dialog.open)
        self.assertNotIn(dialog, self.page.overlay)
        self.assertIsNone(dialog.data._resources)
        self.assertEqual(self.previews(), [])

    def test_fast_scroll_coalesces_to_latest_target(self):
        calls = []
        entered, release = threading.Event(), threading.Event()
        preview = fake_preview(self.root)

        def render(path, **kwargs):
            calls.append(kwargs['page_number'])
            if kwargs['page_number'] == 3:
                entered.set()
                self.assertTrue(release.wait(5))
            return preview(path, **kwargs)

        with patch.object(service, 'create_document_preview', side_effect=render), \
                ThreadPoolExecutor(1) as pool:
            dialog = self.open(near_window=1)
            self.assertEqual(calls, [1, 2])
            calls.clear()
            worker = pool.submit(self.scroll, dialog, 3)
            try:
                self.assertTrue(entered.wait(5))
                for target in (5, 6, 8):
                    self.scroll(dialog, target)  # returns at once: only the target changes
                self.assertEqual(calls, [3])
            finally:
                release.set()
            worker.result(5)
        # Prefetch for 3 stops once 8 is pending; 5 and 6 are never rendered.
        self.assertEqual(calls, [3, 8, 7, 9])
        self.assertEqual(dialog.data.current_request.page_number, 8)
        self.assertEqual(dialog.data.requested_window, (7, 8, 9))
        self.assertEqual(viewer_layout(dialog).page_label.value, 'Página 8 de 10')

    def test_direction_change_prioritizes_travel_direction(self):
        calls = []

        def render(path, **kwargs):
            number = kwargs['page_number']
            calls.append(number)
            image = self.root / f'page-{number}.png'
            image.write_bytes(b'png')
            return dict(ok=True, preview_type='pdf', preview_path=str(image),
                        page_number=number, total_pages=20, zoom=kwargs['zoom'])

        with patch.object(service, 'create_document_preview', side_effect=render):
            dialog = self.open(initial_page=5, near_window=2)
            self.assertEqual(calls, [5, 4, 6, 3, 7])
            calls.clear()
            self.scroll(dialog, 6)
            self.assertEqual(calls, [6, 8])
            calls.clear()
            self.scroll(dialog, 4)
            self.assertEqual(calls, [4, 3, 2])
        self.assertEqual(tuple(dialog.data.loaded_window), (2, 3, 4, 5, 6))

    def test_latest_navigation_wins_over_inflight_scroll(self):
        calls = []
        entered, release, zoom_entered = threading.Event(), threading.Event(), threading.Event()
        preview = fake_preview(self.root)

        def render(path, **kwargs):
            calls.append((kwargs['page_number'], kwargs['zoom']))
            if kwargs['page_number'] == 3 and kwargs['zoom'] == 1.6:
                entered.set()
                self.assertTrue(release.wait(5))
            return preview(path, **kwargs)

        with patch.object(service, 'create_document_preview', side_effect=render):
            dialog = self.open(near_window=1)
            session = dialog.data
            old_view = self.list_view(dialog)
            zoom_in = self.button(dialog, 'Zoom +')
            original = session.render_window

            def observed(request, generation, **kwargs):
                if request.zoom > 1.6:
                    zoom_entered.set()
                return original(request, generation, **kwargs)

            calls.clear()
            with patch.object(session, 'render_window', side_effect=observed), \
                    ThreadPoolExecutor(2) as pool:
                scrolling = pool.submit(self.scroll, old_view, 3)
                try:
                    self.assertTrue(entered.wait(5))
                    zooming = pool.submit(zoom_in.on_click, None)
                    self.assertTrue(zoom_entered.wait(5))
                finally:
                    release.set()
                scrolling.result(5)
                zooming.result(5)
        self.assertEqual([c for c in calls if c[1] == 1.6], [(3, 1.6)])
        self.assertGreater(session.current_request.zoom, 1.6)
        self.assertEqual(session.current_request.page_number, 1)
        self.assertIsNot(self.list_view(dialog), old_view)
        with patch.object(service, 'create_document_preview') as late:
            self.scroll(old_view, 6)
            late.assert_not_called()

    def test_source_change_during_session_is_not_reused(self):
        dialog = self.open(initial_page=2, near_window=1)
        before = {n: r['preview_path'] for n, r in dialog.data.loaded_window.items()}
        stat = self.source.stat()
        changed = self.original.replace(b'/MediaBox[0 0 150 150]', b'/MediaBox[0 0 160 150]')
        self.assertNotEqual(changed, self.original)
        self.assertEqual(len(changed), len(self.original))
        self.source.write_bytes(changed)
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with patch.object(service, 'create_document_preview', wraps=service.create_document_preview) as render:
            self.scroll(dialog, 3)
        self.assertEqual([c.kwargs['page_number'] for c in render.call_args_list], [3, 2, 4])
        after = dialog.data.loaded_window
        for number in (2, 3):
            self.assertNotEqual(before[number], after[number]['preview_path'])
        self.assertEqual(self.source.read_bytes(), changed)

    def test_window_reads_source_once_and_never_writes_it(self):
        reads = []
        original = Path.read_bytes

        def counting(path):
            reads.append(Path(path).resolve())
            return original(path)

        with patch.object(Path, 'read_bytes', autospec=True, side_effect=counting):
            dialog = self.open(near_window=3)
            self.assertEqual(reads.count(self.source.resolve()), 1)
            self.scroll(dialog, 5)
            self.assertEqual(reads.count(self.source.resolve()), 2)
        self.assertEqual(tuple(dialog.data.loaded_window), tuple(range(2, 9)))
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_user_scroll_cancels_pending_scroll_restoration(self):
        self.page.run_task = Mock()
        dialog = self.open(initial_page=7, near_window=0)
        restore = self.page.run_task.call_args.args[0]
        self.scroll(dialog, 3)
        with patch.object(ft.ListView, 'scroll_to', new_callable=AsyncMock) as scroll_to:
            asyncio.run(restore())
            scroll_to.assert_not_awaited()
        self.assertEqual(self.page.run_task.call_count, 1)
        self.assertEqual(dialog.data.requested_window, (3,))

    def test_scroll_patches_window_in_place_and_rebinds_commands(self):
        self.page.run_task = Mock()
        tool = Mock()
        toolbar = Mock(side_effect=lambda request: [ft.TextButton(
            content=ft.Text('Herramienta'), on_click=lambda e, r=request: tool(r.page_number))])
        dialog = self.open(toolbar_actions=toolbar)
        content, view = dialog.content, self.list_view(dialog)
        old_tool = self.button(dialog, 'Herramienta')
        self.scroll(view, 4)
        self.assertIs(dialog.content, content)
        self.assertIs(self.list_view(dialog), view)
        self.assertEqual(self.page.run_task.call_count, 1)
        self.assertEqual(content.data.page_label.value, 'Página 4 de 8')
        self.assertEqual(toolbar.call_args.args[0].page_number, 4)
        # Fixed geometry: the scroll extent never changes, so nothing jumps.
        self.assertEqual(sum(control.height for control in view.controls), 8 * SLOT)
        old_tool.on_click(None)
        tool.assert_not_called()
        self.button(dialog, 'Herramienta').on_click(None)
        tool.assert_called_once_with(4)
        self.button(dialog, 'Siguiente').on_click(None)
        self.assertEqual(dialog.data.current_request.page_number, 5)

    def test_first_page_is_reachable_from_deep_page(self):
        with patch.object(service, 'create_document_preview', wraps=service.create_document_preview) as render:
            dialog = self.open(initial_page=8, near_window=1)
            self.scroll(dialog, 1)
        self.assertEqual(dialog.data.current_request.page_number, 1)
        self.assertEqual(dialog.data.requested_window, (1, 2))
        self.assertTrue({c.kwargs['page_number'] for c in render.call_args_list} <= {1, 2, 7, 8})
        # DV23: fixed toolbar geometry; the first page disables, not removes, 'Anterior'.
        self.assertTrue(self.button(dialog, 'Anterior').disabled)
        self.assertFalse(self.button(dialog, 'Siguiente').disabled)
        self.assertTrue(all(Path(r['preview_path']).is_file() for r in dialog.data.loaded_window.values()))

    def test_failed_scroll_target_keeps_shell_and_recovers(self):
        actual = service.create_document_preview
        calls = []

        def failing(path, **kwargs):
            calls.append(kwargs['page_number'])
            if kwargs['page_number'] == 5:
                raise RuntimeError('render failed')
            return actual(path, **kwargs)

        dialog = self.open(near_window=0)
        content = dialog.content
        with patch.object(service, 'create_document_preview', side_effect=failing):
            self.scroll(dialog, 5)
            self.scroll(dialog, 5)
            self.assertEqual(calls, [5])
            self.assertIs(dialog.content, content)
            self.assertEqual(content.data.page_label.value, 'Página 1 de 8')
            self.scroll(dialog, 1)
            self.assertEqual(dialog.data.current_request.page_number, 1)
            self.scroll(dialog, 6)
        self.assertEqual(dialog.data.current_request.page_number, 6)
        self.assertEqual(content.data.page_label.value, 'Página 6 de 8')
        self.assertTrue(dialog.open)


if __name__ == '__main__':
    unittest.main()
