from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz

from backend.services import document_inbox_service as inbox
from backend.services import document_viewer_service as viewer
from backend.services.document_preview_session import PreviewRequest
from backend.services.document_tools import pdf_tools_service as pdf, safe_file_service
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools.document_tool_result import DocumentToolResult
from frontend.components.document_viewer_modal import open_document_viewer_modal
from frontend.components.pdf_tools_toolbar_adapter import PdfToolsToolbarAdapter


class PdfToolbarTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'original.pdf'
        with fitz.open() as doc:
            doc.new_page()
            doc.new_page()
            doc.save(self.source)
        self.original = self.source.read_bytes()
        self.item = {'id': 17, 'stored_path': str(self.source)}
        self.handler = Mock()
        self.error = Mock()
        self.adapter = PdfToolsToolbarAdapter(lambda request: self.item,
                                             {'rotate': self.handler}, self.error)
        self.request = PreviewRequest(str(self.source), None, 2, 1.6)

    def test_delegates_and_disables_missing_operations(self):
        controls = self.adapter(self.request)
        controls[0].on_click('event')
        self.handler.assert_called_once_with('event', item_id=17)
        self.assertTrue(all(c.disabled and c.on_click is None for c in controls[1:]))
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_missing_pdf_dependency_disables_commands(self):
        with patch.object(pdf, 'PdfReader', None):
            self.assertTrue(all(c.disabled for c in self.adapter(self.request)))

    def test_wrong_document_non_pdf_and_missing_registration_disabled(self):
        registered_item = self.item
        for item, path in [(None, self.source), (registered_item, self.root / 'other.pdf'),
                           (registered_item, self.root / 'image.png')]:
            self.item = item
            self.assertTrue(all(c.disabled for c in self.adapter(
                PreviewRequest(str(path), None, 1, 1.6))))

    def test_rechecks_identity_and_reports_workflow_errors(self):
        control = self.adapter(self.request)[0]
        self.item = {'id': 18, 'stored_path': str(self.source)}
        control.on_click(None)
        self.handler.assert_not_called()
        self.error.assert_called_once()
        self.item['id'] = 17
        self.handler.side_effect = ValueError('service failed')
        control.on_click(None)
        self.assertEqual(str(self.error.call_args.args[0]), 'service failed')

    def test_viewer_invalidates_commands_after_navigation_and_close(self):
        page = SimpleNamespace(overlay=[], update=Mock())
        with patch.object(viewer, 'PREVIEW_DIR', self.root / 'previews'):
            dialog = open_document_viewer_modal(page, str(self.source), toolbar_actions=self.adapter)
            old = dialog.actions[0]
            next(c for c in dialog.actions if c.content.value == 'Siguiente').on_click(None)
            old.on_click(None)
            self.handler.assert_not_called()
            current = dialog.actions[0]
            current.on_click(None)
            self.handler.assert_called_once()
            next(c for c in dialog.actions if c.content.value == 'Cerrar').on_click(None)
            current.on_click(None)
            self.handler.assert_called_once()

    def test_queue_and_reused_dialog_invalidate_old_commands(self):
        second = self.root / 'second.pdf'
        second.write_bytes(self.original)
        items = {str(self.source): self.item,
                 str(second): {'id': 18, 'stored_path': str(second)}}
        adapter = PdfToolsToolbarAdapter(lambda request: items.get(request.path),
                                         {'rotate': self.handler}, self.error)
        page = SimpleNamespace(overlay=[], update=Mock())
        with patch.object(viewer, 'PREVIEW_DIR', self.root / 'previews'):
            dialog = open_document_viewer_modal(
                page, str(self.source), toolbar_actions=adapter,
                queue=[{'path': str(self.source)}, {'path': str(second)}])
            old = dialog.actions[0]
            next(c for c in dialog.actions if c.content.value == 'Doc siguiente').on_click(None)
            old.on_click(None)
            self.handler.assert_not_called()
            current = dialog.actions[0]
            current.on_click('queue')
            self.handler.assert_called_once_with('queue', item_id=18)
            open_document_viewer_modal(page, str(self.source), dialog=dialog,
                                       toolbar_actions=adapter)
            current.on_click(None)
            self.handler.assert_called_once()
            dialog.actions[0].on_click('replacement')
            self.assertEqual(self.handler.call_args.kwargs, {'item_id': 17})
            next(c for c in dialog.actions if c.content.value == 'Cerrar').on_click(None)

    def test_smart_compression_rejects_corrupt_copy_without_removing_candidate(self):
        candidate = self.root / 'candidate.pdf'
        candidate.write_bytes(b'compressed candidate')
        target = self.root / 'final.pdf'
        result = DocumentToolResult.success(
            operation='pdf_compress_basic', source_paths=[self.source], output_path=candidate)
        failure = DocumentToolResult.failure(operation='pdf_compress_rasterized',
                                             source_paths=[self.source], errors=['unavailable'])
        with patch.object(pdf, 'compress_pdf_basic', return_value=result), \
             patch.object(pdf, 'compress_pdf_rasterized', return_value=failure), \
             patch.object(pdf, 'build_output_path', return_value=target), \
             patch.object(pdf.shutil, 'copyfileobj', side_effect=lambda src, dst: dst.write(b'corrupt')):
            outcome = pdf.compress_pdf_smart(self.source)
        self.assertFalse(outcome.ok)
        self.assertIsNone(outcome.output_path)
        self.assertEqual(candidate.read_bytes(), b'compressed candidate')
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_existing_transform_creates_copy_and_refuses_collision(self):
        with patch.object(safe_file_service, 'DOCUMENT_TOOLS_ROOT', self.root / 'tools'):
            result = pdf.rotate_pdf_pages(self.source, page_ranges=[2], degrees=90)
        self.assertTrue(result.ok, result.errors)
        with fitz.open(result.output_path) as doc:
            self.assertEqual(doc[1].rotation, 90)
            self.assertEqual(doc[0].rotation, 0)
        with patch.object(pdf, 'build_output_path', return_value=self.source):
            result = pdf.rotate_pdf_pages(self.source, page_ranges=[1])
        self.assertFalse(result.ok)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_all_existing_pdf_writers_refuse_collision(self):
        operations = [
            lambda: pdf.merge_pdfs([self.source, self.source]),
            lambda: pdf.extract_pdf_pages(self.source, [1]),
            lambda: pdf.remove_pdf_pages(self.source, [1]),
            lambda: pdf.reorder_pdf_pages(self.source, [2, 1]),
            lambda: pdf.split_pdf_by_ranges(self.source, [(1, 1)]),
            lambda: pdf.compress_pdf_basic(self.source),
            lambda: pdf.compress_pdf_rasterized(self.source),
            lambda: pdf.move_pdf_page(self.source, page_number=1, target_position=2),
        ]
        with patch.object(pdf, 'build_output_path', return_value=self.source):
            for operation in operations:
                with self.subTest(operation=operation):
                    self.assertFalse(operation().ok)
                    self.assertEqual(self.source.read_bytes(), self.original)

    def test_existing_inbox_workflow_preserves_traceability(self):
        captured = {}
        def register(file_path, source_type, source_label, metadata_json, client_id, expedient_id):
            captured.update(metadata_json)
            self.assertEqual(source_type, 'generated')
            self.assertEqual(source_label, 'document_tools:pdf_rotate_pages')
            self.assertNotEqual(Path(file_path), self.source)
            with fitz.open(file_path) as doc:
                self.assertEqual(doc[1].rotation, 90)
            return {'id': 99, 'stored_path': file_path}
        with patch.object(inbox_tools, 'get_inbox_item', return_value=self.item), \
             patch.object(inbox_tools, 'import_file_to_inbox', new=register), \
             patch.object(safe_file_service, 'DOCUMENT_TOOLS_ROOT', self.root / 'tools'):
            response = inbox_tools.rotate_pages_in_inbox_pdf(17, page_ranges=[2])
        self.assertTrue(response['ok'])
        self.assertEqual(response['generated_item']['id'], 99)
        self.assertEqual(captured['source_item_ids'], [17])
        self.assertEqual(captured['source_paths'], [str(self.source)])
        self.assertEqual(captured['tool_result']['metadata']['rotated_pages'], [2])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_smart_compression_final_copy_is_exclusive_and_verified(self):
        for collision in (False, True):
            with self.subTest(collision=collision):
                candidate = self.root / 'candidate.pdf'
                candidate.write_bytes(b'compressed candidate')
                target = self.source if collision else self.root / 'final.pdf'
                result = DocumentToolResult.success(
                    operation='pdf_compress_basic', source_paths=[self.source], output_path=candidate)
                failure = DocumentToolResult.failure(operation='pdf_compress_rasterized',
                                                     source_paths=[self.source], errors=['unavailable'])
                with patch.object(pdf, 'compress_pdf_basic', return_value=result), \
                     patch.object(pdf, 'compress_pdf_rasterized', return_value=failure), \
                     patch.object(pdf, 'build_output_path', return_value=target):
                    outcome = pdf.compress_pdf_smart(self.source)
                self.assertEqual(outcome.ok, not collision)
                if collision:
                    self.assertTrue(candidate.exists())
                else:
                    self.assertEqual(target.read_bytes(), b'compressed candidate')
                    self.assertFalse(candidate.exists())
                self.assertEqual(self.source.read_bytes(), self.original)


class CopyVerifyRegisterTests(unittest.TestCase):
    def test_registration_follows_verified_copy_and_failures_never_register(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'source.pdf'
            source.write_bytes(b'original')
            dest = Path(folder) / 'copy.pdf'
            with patch.object(inbox, 'ensure_document_inbox_schema'), \
                 patch.object(inbox, '_find_existing_inbox_item_for_source', return_value=None), \
                 patch.object(inbox, '_unique_destination', return_value=dest), \
                 patch.object(inbox, 'get_connection') as connection:
                def checked_connection():
                    self.assertEqual(dest.read_bytes(), source.read_bytes())
                    raise RuntimeError('registration reached after verification')
                connection.side_effect = checked_connection
                with self.assertRaisesRegex(RuntimeError, 'registration reached'):
                    inbox.import_file_to_inbox(str(source))
                connection.assert_called_once()
                connection.reset_mock()
                with self.assertRaises(FileExistsError):
                    inbox.import_file_to_inbox(str(source))
                connection.assert_not_called()
                dest.unlink()
                with patch.object(inbox.shutil, 'copyfileobj', side_effect=lambda src, dst: dst.write(b'bad')):
                    with self.assertRaisesRegex(ValueError, 'no se ha registrado'):
                        inbox.import_file_to_inbox(str(source))
                connection.assert_not_called()
                self.assertEqual(source.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
