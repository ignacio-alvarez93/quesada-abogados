"""Long navigation through the real cache/session with a cheap fake rasterizer."""
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

import fitz

from backend.services import document_viewer_service as service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest


class ViewerStressTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source.pdf'
        self.source.write_bytes(b'immutable simulated 10000-page document')
        self.original = self.source.read_bytes()
        self.stamp = self.source.stat().st_mtime_ns
        self.renders = Counter()
        document = Mock()
        document.__len__ = Mock(return_value=10000)
        def load(number):
            def raster(**kwargs):
                self.renders[number + 1] += 1
                return Mock(tobytes=Mock(return_value=b'p' * 100))
            return Mock(get_pixmap=raster)
        document.load_page.side_effect = load
        for patcher in (
            patch.object(service, 'PREVIEW_DIR', self.root / 'cache'),
            patch.object(service, 'PREVIEW_CACHE_MAX_PAGES', 7),
            patch.object(service, 'PREVIEW_CACHE_MAX_BYTES', 700),
            patch.object(fitz, 'open', return_value=document),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        touch = service._touch_preview
        def checked_touch(path):
            touch(path)
            self.assert_bounds(path.parent)
        patcher = patch.object(service, '_touch_preview', side_effect=checked_touch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, number, source=None):
        return PreviewRequest(str(source or self.source), None, number, 1.6)

    def session(self, radius=2):
        session = DocumentPreviewSession(near_window=radius)
        self.addCleanup(session.close)
        return session

    def assert_bounds(self, directory):
        files = list(directory.glob('*.png'))
        self.assertLessEqual(len(files), service.PREVIEW_CACHE_MAX_PAGES)
        self.assertLessEqual(sum(p.stat().st_size for p in files), service.PREVIEW_CACHE_MAX_BYTES)
        self.assertEqual(list(directory.glob('*.tmp')), [])

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.source.stat().st_mtime_ns, self.stamp)

    def test_long_navigation_checks_every_publication_and_resident_hit(self):
        session = self.session()
        actual = service.create_document_preview
        def checked(*args, **kwargs):
            directory = kwargs['resources'].directory
            resident = {p.name for p in directory.glob('*.png')}
            before = sum(self.renders.values())
            result = actual(*args, **kwargs)
            self.assert_bounds(directory)
            if result.get('ok') and Path(result['preview_path']).name in resident:
                self.assertEqual(sum(self.renders.values()), before)
            return result
        route = list(range(1, 151)) + list(range(150, 0, -1))
        route += [5000, 5001, 5000, 4999] * 25 + [10000, 1, 9999, 2] * 10
        with patch.object(service, 'create_document_preview', side_effect=checked):
            for target in route:
                result = session.render_window(self.request(target), session.invalidate())
                self.assertTrue(result['ok'])
                expected = tuple(range(max(1, target - 2), min(10000, target + 2) + 1))
                self.assertEqual(tuple(session.loaded_window), expected)
                self.assertEqual(session.requested_window, expected)
                self.assertTrue(all(Path(r['preview_path']).is_file() for r in session.loaded_window.values()))

    def test_prefetch_cannot_evict_current_or_retained_pages_under_tight_budgets(self):
        for pages, byte_budget in ((1, 700), (3, 700), (7, 200)):
            with self.subTest(pages=pages, bytes=byte_budget), patch.object(
                service, 'PREVIEW_CACHE_MAX_PAGES', pages
            ), patch.object(service, 'PREVIEW_CACHE_MAX_BYTES', byte_budget):
                session = self.session(radius=4)
                for target in [500, 501, 500, 499, 9999, 1] * 3:
                    result = session.render_window(self.request(target), session.invalidate())
                    self.assertTrue(result['ok'])
                    self.assertTrue(Path(result['preview_path']).is_file())
                    self.assertIn(target, session.loaded_window)
                    self.assertLessEqual(len(session.loaded_window), min(pages, byte_budget // 100))
                    self.assertTrue(all(Path(r['preview_path']).is_file() for r in session.loaded_window.values()))
                    self.assert_bounds(session._resources.directory)
                session.close()

    def test_lru_matches_reference_model_through_repeated_eviction(self):
        model, paths = OrderedDict(), {}
        for number in list(range(1, 80)) + [78, 75, 79, 81, 80, 75, 82, 83] * 15:
            hit = number in model
            before = self.renders[number]
            result = service.create_document_preview(str(self.source), page_number=number)
            self.assertTrue(result['ok'])
            self.assertEqual(self.renders[number] - before, int(not hit))
            paths[number] = Path(result['preview_path'])
            model[number] = None
            model.move_to_end(number)
            if len(model) > 7:
                model.popitem(last=False)
            self.assertEqual({p for p in paths.values() if p.exists()}, {paths[n] for n in model})
            self.assert_bounds(service.PREVIEW_DIR / 'v2')

    def test_concurrent_same_key_rasterizes_once(self):
        barrier = threading.Barrier(8)
        def render():
            barrier.wait(timeout=5)
            return service.create_document_preview(str(self.source), page_number=5000)
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: render(), range(8)))
        self.assertTrue(all(r['ok'] for r in results))
        self.assertEqual(len({r['preview_path'] for r in results}), 1)
        self.assertEqual(self.renders, {5000: 1})

    def test_obsolete_native_work_cannot_repopulate_replaced_document(self):
        session = self.session()
        session.render_window(self.request(1), session.invalidate())
        old_directory = session._resources.directory
        other = self.root / 'other.pdf'
        other.write_bytes(self.original)
        entered, release = threading.Event(), threading.Event()
        actual = service.create_document_preview
        def blocked(*args, **kwargs):
            if kwargs['page_number'] == 500:
                # Pause inside native rendering, after the service's first
                # freshness check and before cache publication.
                document = fitz.open()
                original_load = document.load_page.side_effect
                def load(number):
                    entered.set()
                    self.assertTrue(release.wait(5))
                    return original_load(number)
                with patch.object(document.load_page, 'side_effect', load):
                    return actual(*args, **kwargs)
            return actual(*args, **kwargs)
        old_generation = session.invalidate()
        with patch.object(service, 'create_document_preview', side_effect=blocked), ThreadPoolExecutor(2) as pool:
            old = pool.submit(session.render_window, self.request(500), old_generation)
            try:
                self.assertTrue(entered.wait(5))
                latest_generation = session.invalidate()
                latest = pool.submit(session.render_window, self.request(9000, other), latest_generation)
            finally:
                release.set()
            self.assertEqual(old.result(5), {})
            self.assertTrue(latest.result(5)['ok'])
        self.assertFalse(old_directory.exists())
        self.assertEqual(session.render_window(self.request(500), old_generation), {})
        session.close()
        self.assertEqual(list((service.PREVIEW_DIR / 'v2').rglob('*.png')), [])
        self.assertEqual(other.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
