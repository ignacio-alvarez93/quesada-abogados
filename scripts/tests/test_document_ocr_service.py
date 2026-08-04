import tempfile
import unittest
from pathlib import Path

from backend.services.document_intelligence import (
    DocumentPageResult,
    DocumentTextResult,
    OcrEngine,
    OcrEngineResult,
    RenderedDocumentPage,
    TesseractCliOcrEngine,
    complete_document_ocr,
    TEXT_SOURCE_NATIVE,
    TEXT_SOURCE_OCR,
    TEXT_SOURCE_NONE,
    STATUS_NATIVE_TEXT,
    STATUS_PARTIAL_OCR_REQUIRED,
)


class FakeOcrEngine(OcrEngine):
    engine_code = "FAKE_OCR"

    def __init__(self, results):
        self.results = dict(results)
        self.calls = []

    def is_available(self):
        return True

    def get_version(self):
        return "fake-1.0"

    def list_languages(self):
        return ["eng", "spa"]

    def extract_image_text(
        self,
        image_path,
        *,
        language="eng",
    ):
        page_number = int(
            Path(image_path)
            .stem
            .split("_")[-1]
        )

        self.calls.append(
            page_number
        )

        return self.results[
            page_number
        ]


class FakeRenderer:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.requested_pages = []

    def render_pages(
        self,
        pdf_path,
        page_numbers,
    ):
        self.requested_pages = list(
            page_numbers
        )

        results = []

        for page_number in page_numbers:
            image_path = (
                self.directory
                / f"page_{page_number}.png"
            )
            image_path.write_bytes(
                b"fake-image"
            )

            results.append(
                RenderedDocumentPage(
                    page_number=page_number,
                    image_path=str(image_path),
                    width=1000,
                    height=1400,
                    dpi=220,
                )
            )

        return results


class DocumentOcrServiceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )
        self.pdf_path = (
            Path(self.temp_dir.name)
            / "document.pdf"
        )
        self.pdf_path.write_bytes(
            b"fake-pdf"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _document(self):
        return DocumentTextResult(
            status=(
                STATUS_PARTIAL_OCR_REQUIRED
            ),
            source_path=str(self.pdf_path),
            source_name="document.pdf",
            source_suffix=".pdf",
            sha256="abc",
            mime_type="application/pdf",
            pages=[
                DocumentPageResult(
                    page_number=1,
                    text=(
                        "Primera página con texto "
                        "nativo suficiente"
                    ),
                    text_source=(
                        TEXT_SOURCE_NATIVE
                    ),
                    confidence=1.0,
                    requires_ocr=False,
                ),
                DocumentPageResult(
                    page_number=2,
                    text="",
                    text_source=(
                        TEXT_SOURCE_NONE
                    ),
                    confidence=0.0,
                    requires_ocr=True,
                ),
            ],
        )

    def test_only_processes_required_pages(self):
        engine = FakeOcrEngine(
            {
                2: OcrEngineResult(
                    text=(
                        "Segunda página recuperada "
                        "mediante reconocimiento OCR"
                    ),
                    confidence=0.91,
                    engine_code="FAKE_OCR",
                    engine_version="fake-1.0",
                    language="spa",
                )
            }
        )
        renderer = FakeRenderer(
            self.temp_dir.name
        )

        result = complete_document_ocr(
            self._document(),
            engine=engine,
            renderer=renderer,
            language="spa",
        )

        self.assertEqual(
            renderer.requested_pages,
            [2],
        )
        self.assertEqual(
            engine.calls,
            [2],
        )
        self.assertEqual(
            result.status,
            STATUS_NATIVE_TEXT,
        )
        self.assertEqual(
            result.pages[0].text_source,
            TEXT_SOURCE_NATIVE,
        )
        self.assertEqual(
            result.pages[1].text_source,
            TEXT_SOURCE_OCR,
        )
        self.assertFalse(
            result.requires_ocr
        )

    def test_keeps_page_pending_when_ocr_is_empty(self):
        engine = FakeOcrEngine(
            {
                2: OcrEngineResult(
                    text="",
                    confidence=0.0,
                    engine_code="FAKE_OCR",
                    language="spa",
                )
            }
        )
        renderer = FakeRenderer(
            self.temp_dir.name
        )

        result = complete_document_ocr(
            self._document(),
            engine=engine,
            renderer=renderer,
            language="spa",
        )

        self.assertEqual(
            result.status,
            STATUS_PARTIAL_OCR_REQUIRED,
        )
        self.assertEqual(
            result.pages_requiring_ocr,
            [2],
        )

    def test_skips_document_without_pending_pages(self):
        document = self._document()
        document.pages[1] = DocumentPageResult(
            page_number=2,
            text=(
                "Segunda página con texto "
                "nativo suficiente"
            ),
            text_source=TEXT_SOURCE_NATIVE,
            confidence=1.0,
            requires_ocr=False,
        )

        engine = FakeOcrEngine({})
        renderer = FakeRenderer(
            self.temp_dir.name
        )

        result = complete_document_ocr(
            document,
            engine=engine,
            renderer=renderer,
        )

        self.assertIs(
            result,
            document,
        )
        self.assertEqual(
            renderer.requested_pages,
            [],
        )

    def test_default_renderer_uses_managed_temporary_directory(
        self,
    ):
        from unittest.mock import patch

        engine = FakeOcrEngine(
            {
                2: OcrEngineResult(
                    text=(
                        "Texto suficiente obtenido "
                        "mediante OCR temporal"
                    ),
                    confidence=0.90,
                    engine_code="FAKE_OCR",
                    language="eng",
                )
            }
        )

        created_directories = []

        class TemporaryRenderer:
            def __init__(
                self,
                *,
                output_directory,
                **kwargs,
            ):
                self.output_directory = Path(
                    output_directory
                )
                created_directories.append(
                    self.output_directory
                )

            def render_pages(
                self,
                pdf_path,
                page_numbers,
            ):
                results = []

                for page_number in page_numbers:
                    image_path = (
                        self.output_directory
                        / f"page_{page_number}.png"
                    )
                    image_path.write_bytes(
                        b"fake-image"
                    )

                    results.append(
                        RenderedDocumentPage(
                            page_number=page_number,
                            image_path=str(image_path),
                            width=1000,
                            height=1400,
                            dpi=220,
                        )
                    )

                return results

        with patch(
            (
                "backend.services."
                "document_intelligence."
                "document_ocr_service."
                "PdfPageRenderer"
            ),
            TemporaryRenderer,
        ):
            result = complete_document_ocr(
                self._document(),
                engine=engine,
                language="eng",
            )

        self.assertEqual(
            result.status,
            STATUS_NATIVE_TEXT,
        )
        self.assertEqual(
            len(created_directories),
            1,
        )
        self.assertFalse(
            created_directories[0].exists()
        )

    def test_detects_installed_tesseract(self):
        engine = TesseractCliOcrEngine()

        self.assertTrue(
            engine.is_available()
        )
        self.assertIn(
            "eng",
            engine.list_languages(),
        )
        self.assertTrue(
            engine.get_version()
        )

    def test_rejects_missing_language(self):
        from PIL import Image

        image_path = (
            Path(self.temp_dir.name)
            / "blank.png"
        )

        Image.new(
            "RGB",
            (100, 100),
            "white",
        ).save(image_path)

        engine = TesseractCliOcrEngine()

        with self.assertRaises(
            ValueError
        ):
            engine.extract_image_text(
                image_path,
                language="spa",
            )


if __name__ == "__main__":
    unittest.main()
