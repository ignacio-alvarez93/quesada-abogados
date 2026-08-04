import tempfile
import unittest
from pathlib import Path

from backend.services import (
    payroll_file_extraction_service
    as payroll_file,
)


class PayrollFileExtractionTest(
    unittest.TestCase
):
    def test_rejects_missing_file(self):
        with self.assertRaises(
            FileNotFoundError
        ):
            payroll_file.extract_payroll_file(
                "missing-payroll.pdf"
            )

    def test_marks_unsupported_format(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payroll.txt"
            path.write_text(
                "NÓMINA",
                encoding="utf-8",
            )

            result = (
                payroll_file.extract_payroll_file(
                    path
                )
            )

        self.assertEqual(
            result["status"],
            "UNSUPPORTED",
        )
        self.assertTrue(
            result["requires_manual_review"]
        )

    def test_empty_pdf_requires_ocr(self):
        try:
            from pypdf import PdfWriter
        except Exception:
            self.skipTest(
                "pypdf no está disponible"
            )

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "empty.pdf"

            writer = PdfWriter()
            writer.add_blank_page(
                width=595,
                height=842,
            )

            with path.open("wb") as file_handle:
                writer.write(file_handle)

            result = (
                payroll_file.extract_payroll_file(
                    path
                )
            )

        self.assertEqual(
            result["status"],
            "OCR_REQUIRED",
        )
        self.assertTrue(
            result["requires_ocr"]
        )
        self.assertEqual(
            result["pages_with_text"],
            0,
        )
        self.assertTrue(
            result["sha256"]
        )

    def test_pdf_text_contract(self):
        try:
            from pypdf import PdfWriter
        except Exception:
            self.skipTest(
                "pypdf no está disponible"
            )

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "blank.pdf"

            writer = PdfWriter()
            writer.add_blank_page(
                width=595,
                height=842,
            )

            with path.open("wb") as file_handle:
                writer.write(file_handle)

            result = (
                payroll_file.extract_pdf_text(path)
            )

        self.assertEqual(
            result["page_count"],
            1,
        )
        self.assertEqual(
            result["pages_with_text"],
            0,
        )
        self.assertEqual(
            result["text"],
            "",
        )

    def test_file_adapter_does_not_apply_values(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payroll.txt"
            path.write_text(
                "NÓMINA",
                encoding="utf-8",
            )

            result = (
                payroll_file.extract_payroll_file(
                    path
                )
            )

        self.assertNotIn(
            "ingresos_mensuales_computables_centimos",
            result,
        )
        self.assertNotIn(
            "applied_to_diagnosis",
            result,
        )

class PayrollBundleContractTest(
    unittest.TestCase
):
    def test_bundle_rejects_missing_file(self):
        with self.assertRaises(
            FileNotFoundError
        ):
            payroll_file.extract_payroll_bundle(
                "missing-bundle.pdf"
            )

    def test_bundle_marks_unsupported_format(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payrolls.txt"
            path.write_text(
                "NÓMINA",
                encoding="utf-8",
            )

            result = (
                payroll_file.extract_payroll_bundle(
                    path
                )
            )

        self.assertEqual(
            result["status"],
            "UNSUPPORTED",
        )
        self.assertEqual(
            result["payroll_count"],
            0,
        )
        self.assertEqual(
            result["payrolls"],
            [],
        )

    def test_blank_bundle_requires_ocr(self):
        try:
            from pypdf import PdfWriter
        except Exception:
            self.skipTest(
                "pypdf no está disponible"
            )

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bundle.pdf"

            writer = PdfWriter()
            writer.add_blank_page(
                width=595,
                height=842,
            )
            writer.add_blank_page(
                width=595,
                height=842,
            )

            with path.open("wb") as file_handle:
                writer.write(file_handle)

            result = (
                payroll_file.extract_payroll_bundle(
                    path
                )
            )

        self.assertEqual(
            result["status"],
            "OCR_REQUIRED",
        )
        self.assertEqual(
            result["page_count"],
            2,
        )
        self.assertEqual(
            result["payroll_count"],
            0,
        )
        self.assertEqual(
            result["unclassified_pages"],
            [1, 2],
        )

    def test_page_text_preserves_page_numbers(self):
        try:
            from pypdf import PdfWriter
        except Exception:
            self.skipTest(
                "pypdf no está disponible"
            )

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pages.pdf"

            writer = PdfWriter()
            writer.add_blank_page(
                width=595,
                height=842,
            )
            writer.add_blank_page(
                width=595,
                height=842,
            )

            with path.open("wb") as file_handle:
                writer.write(file_handle)

            pages = (
                payroll_file.extract_pdf_pages_text(
                    path
                )
            )

        self.assertEqual(
            [
                page["page_number"]
                for page in pages
            ],
            [1, 2],
        )
        self.assertFalse(pages[0]["has_text"])
        self.assertFalse(pages[1]["has_text"])

    def test_bundle_does_not_apply_income(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payrolls.txt"
            path.write_text(
                "NÓMINA",
                encoding="utf-8",
            )

            result = (
                payroll_file.extract_payroll_bundle(
                    path
                )
            )

        self.assertNotIn(
            "ingresos_mensuales_computables_centimos",
            result,
        )
        self.assertNotIn(
            "applied_to_diagnosis",
            result,
        )


if __name__ == "__main__":
    unittest.main()
