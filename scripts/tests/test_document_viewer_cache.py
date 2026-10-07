"""Behavioral cache tests using the canonical service and real PDF rasterizer."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import fitz

from backend.services import document_viewer_service as service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest


class ViewerCacheTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as doc:
            for index in range(12):
                doc.new_page(width=150, height=150).insert_text((20, 30), str(index))
            doc.save(self.source)
        self.original = self.source.read_bytes()
        for name, value in [('PREVIEW_DIR', self.root / 'cache'),
                            ('PREVIEW_CACHE_MAX_PAGES', 4)]:
            patcher = patch.object(service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def render(self, page=1, **kwargs):
        result = service.create_document_preview(str(self.source), page_number=page, **kwargs)
        self.assertTrue(result['ok'], result)
        return result

    def files(self):
        return list((service.PREVIEW_DIR / 'v2').glob('*.png'))

    def test_session_close_releases_cache_and_reopen_is_isolated(self):
        for _ in range(3):
            session = DocumentPreviewSession(near_window=0)
            request = PreviewRequest(str(self.source), None, 1, 1.6)
            result = session.render_window(request, session.invalidate())
            cache = Path(result['preview_path']).parent
            self.assertTrue(cache.exists())
            session.close()
            session.dispose()
            self.assertFalse(cache.exists())
            self.assertEqual(session.loaded_window, {})
            self.assertEqual(session.render_window(request, session.invalidate()), {})
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_replacement_releases_previous_document_only(self):
        sessions = [DocumentPreviewSession(near_window=0) for _ in range(2)]
        self.addCleanup(lambda: [s.close() for s in sessions])
        request = PreviewRequest(str(self.source), None, 1, 1.6)
        first, independent = [s.render_window(request, s.invalidate()) for s in sessions]
        other = self.root / 'other.pdf'
        other.write_bytes(self.original)
        for source in (other, self.source, other):
            new = sessions[0].render_window(PreviewRequest(str(source), None, 1, 1.6), sessions[0].invalidate())
            self.assertFalse(Path(first['preview_path']).exists())
            self.assertTrue(Path(independent['preview_path']).exists())
            first = new
        self.assertEqual(other.read_bytes(), self.original)

    def test_close_during_real_rasterization_never_recreates_cache(self):
        session = DocumentPreviewSession(near_window=0)
        native = fitz.Page.get_pixmap
        def close_during(page, *args, **kwargs):
            bitmap = native(page, *args, **kwargs)
            session.close()
            return bitmap
        with patch.object(fitz.Page, 'get_pixmap', new=close_during):
            result = session.render_window(PreviewRequest(str(self.source), None, 1, 1.6), session.invalidate())
        self.assertEqual(result, {})
        self.assertEqual(list((service.PREVIEW_DIR / 'v2').rglob('*.png')), [])
        self.assertIsNone(session.current_request)

    def test_hit_skips_rasterization_and_key_is_exact(self):
        first = self.render(zoom=1.601)
        with patch.object(fitz.Page, 'get_pixmap', side_effect=AssertionError('cache miss')):
            self.assertEqual(first, self.render(zoom=1.601))
        self.assertNotEqual(first['preview_path'], self.render(zoom=1.609)['preview_path'])
        self.assertEqual(self.render(999)['preview_path'], self.render(12)['preview_path'])

    def test_lru_touch_and_bounded_long_navigation(self):
        paths = [Path(self.render(n)['preview_path']) for n in range(1, 5)]
        self.render(1)
        self.render(5)
        self.assertTrue(paths[0].exists())
        self.assertFalse(paths[1].exists())
        for n in range(1, 13):
            self.render(n)
            self.assertLessEqual(len(self.files()), 4)
        self.assertEqual(self.original, self.source.read_bytes())

    def test_byte_budget_and_oversized_page(self):
        first = Path(self.render()['preview_path'])
        budget = first.stat().st_size * 2
        with patch.object(service, 'PREVIEW_CACHE_MAX_BYTES', budget):
            for n in range(2, 10):
                self.render(n)
                self.assertLessEqual(sum(p.stat().st_size for p in self.files()), budget)
        with patch.object(service, 'PREVIEW_CACHE_MAX_BYTES', 1):
            result = service.create_document_preview(str(self.source))
        self.assertFalse(result['ok'])
        self.assertEqual(self.files(), [])
        self.assertEqual(list((service.PREVIEW_DIR / 'v2').glob('*.tmp')), [])

    def test_real_prefetch_preserves_current_page_with_one_entry_budget(self):
        session = DocumentPreviewSession(near_window=3)
        self.addCleanup(session.close)
        with patch.object(service, 'PREVIEW_CACHE_MAX_PAGES', 1):
            for number in (6, 7, 6, 12, 1):
                result = session.render_window(
                    PreviewRequest(str(self.source), None, number, 1.6), session.invalidate())
                self.assertTrue(result['ok'], result)
                self.assertTrue(Path(result['preview_path']).is_file())
                self.assertEqual(tuple(session.loaded_window), (number,))
                self.assertEqual(list(session._resources.directory.glob('*.png')),
                                 [Path(result['preview_path'])])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_document_content_scope_and_session_isolation(self):
        first = self.render()
        other = self.root / 'other.pdf'
        other.write_bytes(self.original)
        result = service.create_document_preview(str(other))
        self.assertNotEqual(first['preview_path'], result['preview_path'])
        stat = self.source.stat()
        changed = self.original.replace(b'/MediaBox[0 0 150 150]', b'/MediaBox[0 0 160 150]')
        self.assertNotEqual(changed, self.original)
        self.source.write_bytes(changed)
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertNotEqual(first['preview_path'], self.render()['preview_path'])
        with patch.object(service, 'get_expediente_document_root', return_value={
            'exists': True, 'root_path': str(self.root / 'denied')}):
            with self.assertRaises(ValueError):
                self.render(expediente_id=42)
        session = DocumentPreviewSession(near_window=1)
        request = PreviewRequest(str(self.source), None, 6, 1.6)
        session.render_window(request, session.invalidate())
        self.assertEqual(set(session.loaded_window), {5, 6, 7})
        with patch.object(fitz.Page, 'get_pixmap', side_effect=AssertionError('not prefetched')):
            self.assertTrue(session.render(PreviewRequest(str(self.source), None, 7, 1.6),
                                           session.generation)["ok"])
        old = session.generation
        request = PreviewRequest(str(other), None, 2, 1.6)
        session.render_window(request, session.invalidate())
        self.assertEqual(session.current_request.path, str(other))
        self.assertEqual(session.render(request, old), {})

    def test_failed_publication_leaves_no_cache_entry(self):
        with patch.object(Path, 'replace', side_effect=OSError('publication failed')):
            result = service.create_document_preview(str(self.source))
        self.assertFalse(result['ok'])
        self.assertEqual(self.files(), [])
        self.assertEqual(list((service.PREVIEW_DIR / 'v2').glob('*.tmp')), [])
        self.render()
        self.assertEqual(self.original, self.source.read_bytes())

    def test_same_size_same_timestamp_change_invalidates_session_overlap(self):
        session = DocumentPreviewSession(near_window=1)
        request = PreviewRequest(str(self.source), None, 2, 1.6)
        session.render_window(request, session.invalidate())
        old_paths = {n: r['preview_path'] for n, r in session.loaded_window.items()}
        stat = self.source.stat()
        self.source.write_bytes(self.original.replace(b'/MediaBox[0 0 150 150]',
                                                     b'/MediaBox[0 0 160 150]'))
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        session.render_window(request, session.invalidate())
        for number, result in session.loaded_window.items():
            self.assertNotEqual(old_paths[number], result['preview_path'])

    def test_evicted_overlap_is_regenerated(self):
        session = DocumentPreviewSession(near_window=1)
        request = PreviewRequest(str(self.source), None, 2, 1.6)
        session.render_window(request, session.invalidate())
        for n in range(8, 13):
            self.render(n)
        session.render_window(request, session.invalidate())
        self.assertTrue(all(Path(r['preview_path']).is_file() for r in session.loaded_window.values()))


if __name__ == '__main__':
    unittest.main()
