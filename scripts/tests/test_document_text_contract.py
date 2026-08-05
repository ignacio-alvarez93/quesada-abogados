import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.document_intelligence import (
    DocumentPageResult,
    DocumentTextPolicy,
    DocumentTextResult,
    TEXT_SOURCE_NATIVE,
    TEXT_SOURCE_NONE,
    STATUS_NATIVE_TEXT,
    STATUS_PARTIAL_OCR_REQUIRED,
    STATUS_OCR_REQUIRED,
    STATUS_UNSUPPORTED,
)
from backend.services.document_intelligence import (
    document_text_service,
)


class FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class FakeReader:
    def __init__(
        self,
        pages,
        *,
        encrypted=False,
    ):
        self.pages = [
            FakePage(text)
            for text in pages
        ]
        self.is_encrypted = encrypted


class DocumentTextContractTest(
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
            b"fake-pdf-content"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _patch_reader(self, pages):
        return patch.object(
            document_text_service,
            "PdfReader",
            return_value=FakeReader(
                pages
            ),
        )

    def test_page_contract(self):
        page = DocumentPageResult(
            page_number=1,
            text="Texto documental suficiente",
            text_source=TEXT_SOURCE_NATIVE,
            confidence=1.0,
        )

        result = page.to_dict()

        self.assertEqual(
            result["page_number"],
            1,
        )
        self.assertTrue(
            result["has_text"]
        )
        self.assertFalse(
            result["requires_ocr"]
        )

    def test_policy_marks_short_text(self):
        policy = DocumentTextPolicy()

        result = policy.analyze(
            "hola"
        )

        self.assertFalse(
            result["sufficient"]
        )
        self.assertTrue(
            result["reasons"]
        )

    def test_native_pdf(self):
        with self._patch_reader(
            [
                (
                    "Documento con texto nativo "
                    "suficiente para ser procesado"
                ),
                (
                    "Segunda página con contenido "
                    "administrativo extraíble"
                ),
            ]
        ):
            result = (
                document_text_service
                .extract_document_text(
                    self.pdf_path
                )
            )

        self.assertEqual(
            result.status,
            STATUS_NATIVE_TEXT,
        )
        self.assertEqual(
            result.native_text_pages,
            2,
        )
        self.assertFalse(
            result.requires_ocr
        )

    def test_partial_ocr_required(self):
        with self._patch_reader(
            [
                (
                    "Primera página con bastante "
                    "texto documental extraíble"
                ),
                "",
            ]
        ):
            result = (
                document_text_service
                .extract_document_text(
                    self.pdf_path
                )
            )

        self.assertEqual(
            result.status,
            STATUS_PARTIAL_OCR_REQUIRED,
        )
        self.assertEqual(
            result.pages_requiring_ocr,
            [2],
        )
        self.assertEqual(
            result.pages[1].text_source,
            TEXT_SOURCE_NONE,
        )

    def test_full_ocr_required(self):
        with self._patch_reader(
            [
                "",
                "123",
            ]
        ):
            result = (
                document_text_service
                .extract_document_text(
                    self.pdf_path
                )
            )

        self.assertEqual(
            result.status,
            STATUS_OCR_REQUIRED,
        )
        self.assertEqual(
            result.pages_requiring_ocr,
            [1, 2],
        )
        self.assertEqual(
            result.native_text_pages,
            0,
        )

    def test_result_combines_text(self):
        result = DocumentTextResult(
            status=STATUS_NATIVE_TEXT,
            source_path="document.pdf",
            source_name="document.pdf",
            source_suffix=".pdf",
            pages=[
                DocumentPageResult(
                    page_number=1,
                    text="Página uno",
                    text_source=(
                        TEXT_SOURCE_NATIVE
                    ),
                    confidence=1.0,
                ),
                DocumentPageResult(
                    page_number=2,
                    text="Página dos",
                    text_source=(
                        TEXT_SOURCE_NATIVE
                    ),
                    confidence=1.0,
                ),
            ],
        )

        self.assertEqual(
            result.text,
            "Página uno\n\nPágina dos",
        )

    def test_unsupported_file(self):
        text_path = (
            Path(self.temp_dir.name)
            / "document.txt"
        )
        text_path.write_text(
            "contenido",
            encoding="utf-8",
        )

        result = (
            document_text_service
            .extract_document_text(
                text_path
            )
        )

        self.assertEqual(
            result.status,
            STATUS_UNSUPPORTED,
        )
        self.assertFalse(
            result.requires_ocr
        )

    def test_sha256_is_stable(self):
        first = (
            document_text_service
            .calculate_sha256(
                self.pdf_path
            )
        )
        second = (
            document_text_service
            .calculate_sha256(
                self.pdf_path
            )
        )

        self.assertEqual(
            first,
            second,
        )
        self.assertEqual(
            len(first),
            64,
        )


if __name__ == "__main__":
    unittest.main()
