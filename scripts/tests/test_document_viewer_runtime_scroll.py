"""Runtime viewport regressions with Flet's actual dialog stack methods."""
import asyncio
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from frontend.components.document_viewer_modal import open_document_viewer_modal


class RuntimePage:
    def __init__(self):
        self.overlay = []
        self._dialogs = SimpleNamespace(controls=[], update=Mock())
        self.update = Mock()
        self.show_dialog = Mock(side_effect=lambda dialog: ft.Page.show_dialog(self, dialog))
        self.pop_dialog = Mock(side_effect=lambda: ft.Page.pop_dialog(self))

    def dismiss(self, dialog):
        # Transport-free dispatch; the real Flet wrapper removes the stack entry
        # and restores the original handler before forwarding this event.
        async def dispatch(name, event):
            dialog.on_dismiss(event)
        with patch.object(dialog, '_trigger_event', side_effect=dispatch):
            asyncio.run(dialog.on_dismiss(SimpleNamespace(data=None)))


class RuntimeScrollTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'long.pdf'
        with fitz.open() as doc:
            for _ in range(30):
                doc.new_page(width=60, height=80)
            doc.save(self.source)
        self.original = self.source.read_bytes()
        self.page = RuntimePage()
        for patcher in (patch.object(service, 'PREVIEW_DIR', self.root / 'cache'),
                        patch.object(ft.AlertDialog, 'update', Mock())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def open(self, **kwargs):
        return open_document_viewer_modal(self.page, str(self.source), **kwargs)

    def view(self, dialog):
        return dialog.content.content.controls[-1].content

    def click(self, dialog, label):
        next(a for a in dialog.actions if a.content.value == label).on_click(None)

    def scroll(self, view, number, zoom=1.6):
        view.on_scroll(SimpleNamespace(pixels=(number - 1) * (int(1000 * zoom) + 48),
                                       event_type=ft.ScrollType.UPDATE, scroll_delta=1))

    def test_modern_open_close_and_dismiss_do_not_double_pop(self):
        dialog = self.open()
        self.page.show_dialog.assert_called_once_with(dialog)
        self.assertEqual(self.page.overlay, [])
        self.assertIn(dialog, self.page._dialogs.controls)
        dialog.data.invalidate()
        self.click(dialog, 'Cerrar')
        self.page.pop_dialog.assert_called_once()
        self.assertFalse(dialog.open)
        self.assertIsNone(dialog.data.current_request)
        self.page.dismiss(dialog)
        self.page.pop_dialog.assert_called_once()
        self.assertEqual(self.page._dialogs.controls, [])

    def test_external_dismiss_only_disposes(self):
        dialog = self.open()
        self.page.dismiss(dialog)
        self.page.pop_dialog.assert_not_called()
        self.assertTrue(dialog.data._closed)
        self.assertEqual(self.page._dialogs.controls, [])

    def test_repeated_open_close_has_no_ghost_state(self):
        for _ in range(4):
            dialog = self.open()
            self.click(dialog, 'Cerrar')
            self.page.dismiss(dialog)
            self.assertEqual(self.page._dialogs.controls, [])
            self.assertEqual(self.page.overlay, [])

    def test_scroll_keeps_shell_view_toolbar_and_extent_without_restore_tasks(self):
        dialog = self.open(initial_page=5, near_window=1)
        shell, column, actions, view = dialog.content, dialog.content.content, dialog.actions, self.view(dialog)
        self.page.run_task = Mock()
        # Execute the one admitted worker; no scroll restoration is scheduled.
        self.scroll(view, 12)
        self.page.run_task.assert_called_once()
        asyncio.run(self.page.run_task.call_args.args[0]())
        self.assertIs(dialog.content, shell)
        self.assertIs(dialog.content.content, column)
        self.assertIs(dialog.actions, actions)
        self.assertIs(self.view(dialog), view)
        self.assertEqual((shell.width, shell.height), (980, 680))
        self.assertEqual(sum(c.height for c in view.controls), 30 * 1648)
        self.page.show_dialog.assert_called_once()
        self.assertEqual(dialog.data.current_request.page_number, 12)

    def test_initial_zero_and_metrics_cannot_jump_deep_page(self):
        dialog = self.open(initial_page=18)
        view = self.view(dialog)
        for event in (SimpleNamespace(pixels=0), SimpleNamespace(pixels=0, event_type=ft.ScrollType.START)):
            view.on_scroll(event)
            self.assertEqual(dialog.data.current_request.page_number, 18)
        self.scroll(view, 19)
        self.scroll(view, 1)
        self.assertEqual(dialog.data.current_request.page_number, 1)

    def exercise_pending(self, targets, close=False):
        dialog = self.open(initial_page=5, near_window=1)
        view = self.view(dialog)
        entered, release = threading.Event(), threading.Event()
        actual = service.create_document_preview
        calls, publications = [], []
        def render(path, **kwargs):
            calls.append(kwargs['page_number'])
            if kwargs['page_number'] == 7:
                entered.set()
                self.assertTrue(release.wait(5))
            return actual(path, **kwargs)
        self.page.update.side_effect = lambda: publications.append(
            dialog.data.current_request.page_number if dialog.data.current_request else None)
        with patch.object(service, 'create_document_preview', side_effect=render), ThreadPoolExecutor(1) as pool:
            worker = pool.submit(self.scroll, view, 7)
            try:
                self.assertTrue(entered.wait(5))
                for target in targets:
                    self.scroll(view, target)
                self.assertEqual(calls, [7])
                if close:
                    self.click(dialog, 'Cerrar')
            finally:
                release.set()
            worker.result(5)
        if close:
            self.assertEqual(calls, [7])
            self.assertTrue(dialog.data._closed)
            self.assertIsNone(dialog.content)
        else:
            latest = targets[-1]
            self.assertEqual(dialog.data.current_request.page_number, latest)
            self.assertEqual(calls[1], latest)
            self.assertNotIn(7, publications)
            self.assertEqual(publications[-1], latest)
            self.assertLessEqual(len(calls), 4)
        return dialog

    def test_latest_target_wins_5_7_10_14_18(self):
        self.exercise_pending([10, 14, 18])

    def test_rapid_forward_back_is_deterministic(self):
        self.exercise_pending([18, 10, 22, 3, 14, 2])

    def test_close_invalidates_pending_work(self):
        self.exercise_pending([10, 14, 18], close=True)

    def test_single_scheduled_pipeline_for_many_events(self):
        dialog = self.open(initial_page=5, near_window=0)
        self.page.run_task = Mock()
        for target in range(6, 30):
            self.scroll(self.view(dialog), target)
        self.page.run_task.assert_called_once()
        with patch.object(service, 'create_document_preview', wraps=service.create_document_preview) as render:
            asyncio.run(self.page.run_task.call_args.args[0]())
            self.assertEqual([c.kwargs['page_number'] for c in render.call_args_list], [29])

    def test_target_published_before_neighbors_and_prefetch_bounded(self):
        dialog = self.open(initial_page=5, near_window=2)
        actual = service.create_document_preview
        calls = []
        def render(path, **kwargs):
            number = kwargs['page_number']
            calls.append(number)
            if number != 18:
                self.assertEqual(dialog.data.current_request.page_number, 18)
                self.assertIn('18', dialog.content.content.controls[2].value)
                self.assertEqual(tuple(dialog.data.loaded_window), (18,))
            return actual(path, **kwargs)
        with patch.object(service, 'create_document_preview', side_effect=render):
            self.scroll(self.view(dialog), 18)
        self.assertEqual(calls[0], 18)
        self.assertEqual(set(calls), set(range(16, 21)))
        self.assertLessEqual(len(self.view(dialog).controls), 7)

    def test_zoom_navigation_and_toolbar_follow_scrolled_page(self):
        toolbar = Mock(return_value=[])
        dialog = self.open(toolbar_actions=toolbar)
        self.scroll(self.view(dialog), 18)
        self.assertEqual(toolbar.call_args.args[0].page_number, 18)
        shell = dialog.content
        self.click(dialog, 'Zoom +')
        self.assertEqual(dialog.data.current_request.page_number, 18)
        self.assertIs(dialog.content, shell)
        self.click(dialog, 'Zoom -')
        self.assertEqual(dialog.data.current_request.page_number, 18)
        self.click(dialog, 'Anterior')
        self.assertEqual(dialog.data.current_request.page_number, 17)
        self.click(dialog, 'Siguiente')
        self.assertEqual(dialog.data.current_request.page_number, 18)
        self.click(dialog, 'Cerrar')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_initial_target_opens_before_neighbor_render(self):
        actual = service.create_document_preview
        def render(path, **kwargs):
            if kwargs['page_number'] != 18:
                self.assertEqual(len(self.page._dialogs.controls), 1)
                dialog = self.page._dialogs.controls[0]
                self.assertEqual(dialog.data.current_request.page_number, 18)
                self.assertTrue(dialog.open)
            return actual(path, **kwargs)
        with patch.object(service, 'create_document_preview', side_effect=render):
            self.open(initial_page=18)

    def test_failed_obsolete_render_still_drains_latest_target(self):
        dialog = self.open(initial_page=5, near_window=0)
        view = self.view(dialog)
        actual = service.create_document_preview
        def render(path, **kwargs):
            if kwargs['page_number'] == 7:
                self.scroll(view, 18)
                raise OSError('obsolete render failed')
            return actual(path, **kwargs)
        with patch.object(service, 'create_document_preview', side_effect=render):
            self.scroll(view, 7)
        self.assertEqual(dialog.data.current_request.page_number, 18)

    def test_real_user_update_can_scroll_directly_from_deep_page_to_one(self):
        dialog = self.open(initial_page=18)
        self.scroll(self.view(dialog), 1)
        self.assertEqual(dialog.data.current_request.page_number, 1)

    def test_scheduled_restore_cannot_bounce_after_newer_scroll(self):
        self.page.run_task = Mock()
        dialog = self.open(initial_page=18)
        restore = self.page.run_task.call_args.args[0]
        self.scroll(self.view(dialog), 22)
        pipeline = self.page.run_task.call_args.args[0]
        asyncio.run(pipeline())
        from unittest.mock import AsyncMock
        with patch.object(ft.ListView, 'scroll_to', new_callable=AsyncMock) as scroll_to:
            asyncio.run(restore())
            scroll_to.assert_not_awaited()
        self.assertEqual(dialog.data.current_request.page_number, 22)

    def test_source_snapshot_reused_and_changed_source_rehashed(self):
        actual = service.hashlib.sha256
        source_hashes = []
        def digest(data):
            if data.startswith(b'%PDF'):
                source_hashes.append(data)
            return actual(data)
        with patch.object(service.hashlib, 'sha256', side_effect=digest):
            dialog = self.open()
            for number in (5, 10, 18, 3):
                self.scroll(self.view(dialog), number)
            self.assertEqual(len(source_hashes), 1)
            self.source.write_bytes(self.original + b'\n')
            self.scroll(self.view(dialog), 14)
            self.assertEqual(len(source_hashes), 2)
            self.assertEqual(source_hashes[-1], self.original + b'\n')


if __name__ == '__main__':
    unittest.main()
