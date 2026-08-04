import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services import (
    payroll_file_extraction_service
    as payroll_file,
)
from backend.services.document_intelligence import (
    DocumentPageResult,
    DocumentTextResult,
    STATUS_NATIVE_TEXT,
    STATUS_PARTIAL_OCR_REQUIRED,
    TEXT_SOURCE_NATIVE,
    TEXT_SOURCE_OCR,
    TEXT_SOURCE_NONE,
)


PAYROLL_TEXT = """
NÓMINA
EMPRESA: SERVICIOS ASTURIAS SL
TRABAJADOR: JUAN PÉREZ GARCÍA
PERIODO: 07/2026
TOTAL DEVENGADO 1.540,00
TOTAL DEDUCCIONES 320,00
LÍQUIDO A PERCIBIR 1.220,00
"""


class PayrollDocumentIntelligenceTest(
    unittest.TestCase
):
    def _document_result(
        self,
        *,
        pages,
        status=STATUS_NATIVE_TEXT,
    ):
        return DocumentTextResult(
            status=status,
            source_path="nominas.pdf",
            source_name="nominas.pdf",
            source_suffix=".pdf",
            sha256="abc123",
            mime_type="application/pdf",
            pages=pages,
            metadata={
                "cache": {
                    "cache_hit": False,
                }
            },
        )

    def test_adapts_native_and_ocr_pages(self):
        result = self._document_result(
            pages=[
                DocumentPageResult(
                    page_number=1,
                    text=PAYROLL_TEXT,
                    text_source=(
                        TEXT_SOURCE_NATIVE
                    ),
                    confidence=1.0,
                ),
                DocumentPageResult(
                    page_number=2,
                    text=PAYROLL_TEXT.replace(
                        "07/2026",
                        "08/2026",
                    ),
                    text_source=(
                        TEXT_SOURCE_OCR
                    ),
                    confidence=0.91,
                    language="spa",
                ),
            ]
        )

        bundle = (
            payroll_file
            .extract_payroll_bundle_from_document_result(
                result
            )
        )

        self.assertEqual(
            bundle["status"],
            "EXTRACTED",
        )
        self.assertEqual(
            bundle["payroll_count"],
            2,
        )
        self.assertEqual(
            bundle["native_text_pages"],
            1,
        )
        self.assertEqual(
            bundle["ocr_text_pages"],
            1,
        )
        self.assertEqual(
            bundle["payrolls"][0][
                "source_pages"
            ],
            [1],
        )
        self.assertEqual(
            bundle["payrolls"][1][
                "document_text_source"
            ],
            "OCR",
        )
        self.assertAlmostEqual(
            bundle["payrolls"][1][
                "document_text_confidence"
            ],
            0.91,
        )

    def test_preserves_unresolved_pages(self):
        result = self._document_result(
            status=(
                STATUS_PARTIAL_OCR_REQUIRED
            ),
            pages=[
                DocumentPageResult(
                    page_number=1,
                    text=PAYROLL_TEXT,
                    text_source=(
                        TEXT_SOURCE_NATIVE
                    ),
                    confidence=1.0,
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

        bundle = (
            payroll_file
            .extract_payroll_bundle_from_document_result(
                result
            )
        )

        self.assertEqual(
            bundle["payroll_count"],
            1,
        )
        self.assertTrue(
            bundle["requires_ocr"]
        )
        self.assertEqual(
            bundle["unclassified_pages"],
            [2],
        )

    def test_file_bundle_uses_document_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nominas.pdf"
            path.write_bytes(
                b"fake-pdf-content"
            )

            document_result = (
                self._document_result(
                    pages=[
                        DocumentPageResult(
                            page_number=1,
                            text=PAYROLL_TEXT,
                            text_source=(
                                TEXT_SOURCE_OCR
                            ),
                            confidence=0.93,
                            language="spa",
                        )
                    ]
                )
            )

            fake_engine = object()

            with patch.object(
                payroll_file
                .document_intelligence_service,
                "process_document",
                return_value=document_result,
            ) as processor:
                bundle = (
                    payroll_file
                    .extract_payroll_bundle(
                        path,
                        engine=fake_engine,
                        language="spa",
                        render_dpi=240,
                        intelligence_db_path=(
                            Path(temp) / "ocr.db"
                        ),
                        force_reprocess=True,
                    )
                )

        processor.assert_called_once()

        kwargs = processor.call_args.kwargs

        self.assertIs(
            kwargs["engine"],
            fake_engine,
        )
        self.assertEqual(
            kwargs["language"],
            "spa",
        )
        self.assertEqual(
            kwargs["render_dpi"],
            240,
        )
        self.assertTrue(
            kwargs["force_reprocess"]
        )
        self.assertEqual(
            bundle["payroll_count"],
            1,
        )
        self.assertEqual(
            bundle["ocr_text_pages"],
            1,
        )

    def test_rejects_non_document_result(self):
        with self.assertRaises(TypeError):
            (
                payroll_file
                .extract_payroll_bundle_from_document_result(
                    {}
                )
            )


if __name__ == "__main__":
    unittest.main()
