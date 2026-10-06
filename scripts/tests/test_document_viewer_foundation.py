import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fitz
import flet as ft

from backend.services import document_viewer_service as service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest
from backend.services.document_tools import pdf_tools_service, safe_file_service
from frontend.components.document_viewer_modal import open_document_viewer_modal


class ViewerFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdf'
        with fitz.open() as document:
            for index in range(8):
                document.new_page().insert_text((40, 40), f'Page {index + 1}')
            document.save(self.source)
        self.original = self.source.read_bytes()
        self.preview_patch = patch.object(service, 'PREVIEW_DIR', self.root / 'previews')
        self.preview_patch.start()
        self.addCleanup(self.preview_patch.stop)
        self.page = SimpleNamespace(overlay=[], update=Mock())

    def open(self, **kwargs):
        return open_document_viewer_modal(self.page, str(self.source), **kwargs)

    def button(self, dialog, label):
        return next(action for action in dialog.actions if action.content.value == label)

    def list_view(self, dialog):
        return dialog.content.content.controls[-1].content

    def test_construct_open_multipage_scroll_and_close(self):
        with patch.object(service, 'create_document_preview', wraps=service.create_document_preview) as render:
            dialog = self.open()
            self.assertTrue(dialog.open)
            self.assertIn(dialog, self.page.overlay)
            self.assertEqual([c.kwargs['page_number'] for c in render.call_args_list], [1, 2, 3, 4])
            view = self.list_view(dialog)
            self.assertIsInstance(view, ft.ListView)
            view.on_scroll(SimpleNamespace(pixels=1000, max_scroll_extent=1000))
            self.assertEqual([c.kwargs['page_number'] for c in render.call_args_list][-3:], [5, 6, 7])
            self.button(dialog, 'Cerrar').on_click(None)
            calls = render.call_count
            view.on_scroll(SimpleNamespace(pixels=1000, max_scroll_extent=1000))
            self.assertEqual(render.call_count, calls)
            self.assertNotIn(dialog, self.page.overlay)
            self.assertFalse(dialog.open)
        self.assertEqual(self.original, self.source.read_bytes())

    def test_zoom_invalidates_old_scroll_callbacks(self):
        dialog = self.open()
        old_view = self.list_view(dialog)
        self.button(dialog, 'Zoom +').on_click(None)
        with patch.object(service, 'create_document_preview') as render:
            old_view.on_scroll(SimpleNamespace(pixels=1000, max_scroll_extent=1000))
            render.assert_not_called()

    def test_queue_toolbar_and_system_open_follow_current_document(self):
        other = self.root / 'other.pdf'
        other.write_bytes(self.original)
        toolbar = Mock(return_value=[])
        dialog = self.open(queue=[{'path': str(self.source)}, {'path': str(other)}], toolbar_actions=toolbar)
        self.button(dialog, 'Doc siguiente').on_click(None)
        self.assertEqual(toolbar.call_args.args[0].path, str(other))
        with patch.object(service, 'open_document') as opener:
            self.button(dialog, 'Abrir con visor del sistema').on_click(None)
            opener.assert_called_once_with(str(other), expediente_id=None)
        self.button(dialog, 'Doc anterior').on_click(None)
        self.assertEqual(toolbar.call_args.args[0].path, str(self.source))

    def test_reusing_dialog_invalidates_previous_session(self):
        dialog = self.open()
        old_view = self.list_view(dialog)
        self.assertIs(self.open(dialog=dialog), dialog)
        with patch.object(service, 'create_document_preview') as render:
            old_view.on_scroll(SimpleNamespace(pixels=1000, max_scroll_extent=1000))
            render.assert_not_called()
        self.button(dialog, 'Cerrar').on_click(None)
        self.assertIn(dialog, self.page.overlay)

    def test_navigation_preserves_loaded_extent(self):
        dialog = self.open()
        self.list_view(dialog).on_scroll(SimpleNamespace(pixels=1000, max_scroll_extent=1000))
        with patch.object(service, 'create_document_preview', wraps=service.create_document_preview) as render:
            self.button(dialog, 'Siguiente').on_click(None)
        self.assertEqual(set(c.kwargs['page_number'] for c in render.call_args_list), set(range(1, 8)))

    def test_old_buttons_cannot_reopen_or_replace_reused_dialog(self):
        dialog = self.open()
        old_next = self.button(dialog, 'Siguiente')
        old_close = self.button(dialog, 'Cerrar')
        self.open(dialog=dialog)
        content = dialog.content
        with patch.object(service, 'create_document_preview') as render:
            old_next.on_click(None)
            old_close.on_click(None)
            render.assert_not_called()
        self.assertIs(dialog.content, content)
        self.assertTrue(dialog.open)
        next_button = self.button(dialog, 'Siguiente')
        self.button(dialog, 'Cerrar').on_click(None)
        with patch.object(service, 'create_document_preview') as render:
            next_button.on_click(None)
            render.assert_not_called()
        self.assertFalse(dialog.open)

    def test_page_navigation_and_zoom_bounds(self):
        dialog = self.open(initial_page=2, initial_zoom=3.5)
        with patch.object(service, 'create_document_preview', wraps=service.create_document_preview) as render:
            self.button(dialog, 'Siguiente').on_click(None)
            self.assertEqual(render.call_args_list[0].kwargs['page_number'], 3)
            self.button(dialog, 'Zoom +').on_click(None)
            self.assertEqual(render.call_args.kwargs['zoom'], 3.5)

    def test_missing_and_bad_document_contracts(self):
        with self.assertRaises(FileNotFoundError):
            service.create_document_preview(str(self.root / 'missing.pdf'))
        bad = self.root / 'bad.pdf'
        bad.write_bytes(b'not a PDF')
        self.assertFalse(service.create_document_preview(str(bad))['ok'])
        dialog = open_document_viewer_modal(self.page, str(bad))
        self.assertIn('No se pudo generar', dialog.content.content.controls[-1].content.value)
        error = Mock()
        open_document_viewer_modal(self.page, str(self.root / 'missing.pdf'), on_error=error)
        error.assert_called_once()

    def test_image_and_unsupported_preview(self):
        image = self.root / 'image.png'
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 5, 5), False)
        pix.save(image)
        self.assertEqual(service.create_document_preview(str(image))['preview_path'], str(image))
        dialog = open_document_viewer_modal(self.page, str(image))
        self.assertTrue(dialog.open)
        other = self.root / 'file.txt'
        other.write_text('text')
        self.assertEqual(service.create_document_preview(str(other))['preview_type'], 'unsupported')

    def test_access_validation_applies_to_preview_and_system_open(self):
        with patch.object(service, 'get_expediente_document_root', return_value={
            'exists': True, 'root_path': str(self.root / 'restricted'),
        }):
            for action in (service.create_document_preview, service.open_document):
                with self.assertRaises(ValueError):
                    action(str(self.source), expediente_id=42)

    def test_system_open_uses_validated_path(self):
        with patch.object(service.platform, 'system', return_value='Windows'), patch.object(service.os, 'startfile', create=True) as opener:
            self.assertTrue(service.open_document(str(self.source))['ok'])
            opener.assert_called_once_with(str(self.source.resolve()))

    def test_render_failure_closes_pdf_handle(self):
        document = Mock()
        document.__len__ = Mock(return_value=8)
        document.load_page.side_effect = RuntimeError('render failed')
        with patch.object(fitz, 'open', return_value=document):
            result = service.create_document_preview(str(self.source))
        self.assertFalse(result['ok'])
        document.close.assert_called_once()

    def test_single_page_and_page_clamping(self):
        single = self.root / 'single.pdf'
        with fitz.open() as document:
            document.new_page()
            document.save(single)
        result = service.create_document_preview(str(single), page_number=500)
        self.assertEqual((result['page_number'], result['total_pages']), (1, 1))
        dialog = open_document_viewer_modal(self.page, str(single))
        labels = [action.content.value for action in dialog.actions]
        self.assertNotIn('Siguiente', labels)
        self.assertNotIn('Anterior', labels)

    def test_inbox_callers_still_use_canonical_viewer(self):
        tree = ast.parse(Path('frontend/views/document_inbox_view.py').read_text(encoding='utf-8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'open_document_viewer_modal']
        self.assertEqual(len(calls), 3)

    def test_obsolete_request_is_not_started_or_delivered(self):
        session = DocumentPreviewSession()
        request = PreviewRequest(str(self.source), None, 1, 1.6)
        generation = session.invalidate()
        session.invalidate()
        with patch.object(service, 'create_document_preview') as render:
            self.assertEqual(session.render(request, generation), {})
            render.assert_not_called()
        def obsolete(*args, **kwargs):
            session.invalidate()
            return {'ok': True}
        with patch.object(service, 'create_document_preview', side_effect=obsolete):
            self.assertEqual(session.render(request, session.generation), {})

    def test_pdf_tools_produce_separate_copy(self):
        with patch.object(safe_file_service, 'DOCUMENT_TOOLS_ROOT', self.root / 'tools'):
            result = pdf_tools_service.rotate_pdf_pages(str(self.source), page_ranges='1,3', degrees=90)
        self.assertTrue(result.ok, result.errors)
        self.assertNotEqual(Path(result.output_path).resolve(), self.source.resolve())
        self.assertEqual(self.original, self.source.read_bytes())
        with fitz.open(result.output_path) as document:
            self.assertEqual(len(document), 8)
            self.assertEqual(document[0].rotation, 90)
            self.assertEqual(document[1].rotation, 0)

    def test_expedients_adapter_executes_canonical_contract(self):
        tree = ast.parse(Path('frontend/views/expedients_view.py').read_text(encoding='utf-8'))
        adapter = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'show_document_preview')
        canonical, error, dialog = Mock(), Mock(), object()
        scope = dict(open_document_viewer_modal=canonical, page=self.page,
                     state={'editing_id': 42}, document_viewer_dialog=dialog, show_form_error=error)
        exec(compile(ast.Module(body=[adapter], type_ignores=[]), '<adapter>', 'exec'), scope)
        queue = [{'path': str(self.source)}]
        scope['show_document_preview'](str(self.source), 'Title', page_number=3, zoom=2, queue=queue)
        canonical.assert_called_once_with(self.page, str(self.source), title='Title', expediente_id=42,
            initial_page=3, initial_zoom=2, queue=queue, queue_index=0, dialog=dialog, on_error=error)
        scope['state'].clear()
        scope['show_document_preview'](str(self.source))
        error.assert_called_once()
        self.assertEqual(canonical.call_count, 1)
        # Five external caller sites survive; the former self-recursive engine is gone.
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'show_document_preview']
        self.assertEqual(len(calls), 5)
        self.assertNotIn('create_document_preview', ast.unparse(tree))


if __name__ == '__main__':
    unittest.main()
