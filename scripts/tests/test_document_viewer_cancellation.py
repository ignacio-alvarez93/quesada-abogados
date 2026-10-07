"""Deterministic event barriers: no sleeps or native render timing assumptions."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.services import document_viewer_service as service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest
from frontend.components.document_viewer_modal import open_document_viewer_modal


def result(number):
    return dict(ok=True, preview_type='pdf', preview_path=f'{number}.png',
                page_number=number, total_pages=10, zoom=1.6)


class CancellationTests(unittest.TestCase):
    def test_superseded_waiters_finish_before_old_render_and_only_latest_runs(self):
        session = DocumentPreviewSession(near_window=0)
        entered, release = threading.Event(), threading.Event()
        calls = []

        def render(path, **kwargs):
            number = kwargs['page_number']
            calls.append(number)
            if number == 1:
                entered.set()
                self.assertTrue(release.wait(5))
            return result(number)

        def request(number):
            return PreviewRequest(f'source-{number}.pdf', None, number, 1.6)

        with patch.object(service, 'create_document_preview', side_effect=render), ThreadPoolExecutor(3) as pool:
            old = pool.submit(session.render_window, request(1), session.invalidate())
            try:
                self.assertTrue(entered.wait(5))
                middle = pool.submit(session.render_window, request(2), session.invalidate())
                latest_generation = session.invalidate()
                latest = pool.submit(session.render_window, request(3), latest_generation)
                self.assertEqual(middle.result(5), {})  # completes before request 1
                self.assertFalse(old.done())
            finally:
                release.set()
            self.assertEqual(old.result(5), {})
            self.assertEqual(latest.result(5)['page_number'], 3)
        self.assertEqual(calls, [1, 3])
        self.assertEqual(session.current_request.page_number, 3)
        self.assertEqual(session.current_request.path, "source-3.pdf")
        self.assertEqual(tuple(session.loaded_window), (3,))

    def test_close_during_native_render_discards_result_and_neighbors(self):
        session = DocumentPreviewSession()
        entered, release = threading.Event(), threading.Event()

        def render(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return result(4)

        with patch.object(service, 'create_document_preview', side_effect=render) as renderer, ThreadPoolExecutor(1) as pool:
            future = pool.submit(session.render_window, PreviewRequest('source.pdf', None, 4, 1.6), session.invalidate())
            try:
                self.assertTrue(entered.wait(5))
                session.close()
            finally:
                release.set()
            self.assertEqual(future.result(5), {})
            self.assertEqual(renderer.call_count, 1)
        self.assertEqual(session.loaded_window, {})
        self.assertIsNone(session.current_request)
        self.assertFalse(session._active)

    def test_late_ui_completion_cannot_replace_newer_viewport(self):
        page = SimpleNamespace(overlay=[], update=Mock())
        entered, release = threading.Event(), threading.Event()
        with patch.object(service, 'create_document_preview', return_value=result(1)):
            dialog = open_document_viewer_modal(page, 'source.pdf', near_window=0)
        actions = {a.content.value: a for a in dialog.actions}

        def delayed(request, generation):
            if request.page_number == 2:
                entered.set()
                self.assertTrue(release.wait(5))
            value = result(request.page_number)
            value['zoom'] = request.zoom
            return value

        with patch.object(dialog.data, 'render_window', side_effect=delayed), ThreadPoolExecutor(1) as pool:
            old = pool.submit(actions['Siguiente'].on_click, None)
            try:
                self.assertTrue(entered.wait(5))
                actions['Zoom +'].on_click(None)
                newest_content = dialog.content
                updates = page.update.call_count
            finally:
                release.set()
            old.result(5)
        self.assertIs(dialog.content, newest_content)
        self.assertEqual(page.update.call_count, updates)

    def test_close_wakes_waiter_and_is_idempotent(self):
        session = DocumentPreviewSession(near_window=0)
        entered, release = threading.Event(), threading.Event()
        def render(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return result(1)
        request = PreviewRequest('source.pdf', None, 1, 1.6)
        with patch.object(service, 'create_document_preview', side_effect=render), ThreadPoolExecutor(2) as pool:
            active = pool.submit(session.render_window, request, session.invalidate())
            try:
                self.assertTrue(entered.wait(5))
                waiting = pool.submit(session.render_window, request, session.invalidate())
                session.close()
                generation = session.generation
                session.dispose()
                self.assertEqual(session.generation, generation)
                self.assertEqual(waiting.result(5), {})
            finally:
                release.set()
            self.assertEqual(active.result(5), {})
        self.assertIsNone(session._resources)

    def test_exception_releases_admission_for_next_request(self):
        session = DocumentPreviewSession(near_window=0)
        request = PreviewRequest('source.pdf', None, 1, 1.6)
        with patch.object(service, 'create_document_preview', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                session.render_window(request, session.invalidate())
        with patch.object(service, 'create_document_preview', return_value=result(1)):
            self.assertTrue(session.render_window(request, session.invalidate())['ok'])


if __name__ == '__main__':
    unittest.main()
