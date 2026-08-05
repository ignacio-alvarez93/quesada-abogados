import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.services.document_intelligence import (
    DocumentPageResult,
    DocumentTextResult,
    OcrEngine,
    OcrEngineResult,
    STATUS_NATIVE_TEXT,
    TEXT_SOURCE_NATIVE,
    process_document,
)
from backend.services.document_intelligence import (
    document_ocr_repository,
)
from backend.services.document_intelligence import (
    document_intelligence_service,
)


class FakeEngine(OcrEngine):
    engine_code = "FAKE_CACHE_OCR"

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def get_version(self):
        return "fake-cache-1"

    def list_languages(self):
        return ["eng"]

    def extract_image_text(
        self,
        image_path,
        *,
        language="eng",
    ):
        self.calls += 1

        return OcrEngineResult(
            text=(
                "Texto OCR suficientemente largo "
                "para validar la página"
            ),
            confidence=0.90,
            engine_code=self.engine_code,
            engine_version=self.get_version(),
            language=language,
        )


class DocumentOcrPersistenceTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_path = (
            Path(self.temp_dir.name)
            / "test.db"
        )

        self.document_path = (
            Path(self.temp_dir.name)
            / "document.pdf"
        )

        self.document_path.write_bytes(
            b"fake-document-content"
        )

        document_ocr_repository.ensure_schema(
            db_path=self.db_path
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _native_result(self):
        return DocumentTextResult(
            status=STATUS_NATIVE_TEXT,
            source_path=str(
                self.document_path
            ),
            source_name="document.pdf",
            source_suffix=".pdf",
            sha256=(
                document_intelligence_service
                .calculate_sha256(
                    self.document_path
                )
            ),
            mime_type="application/pdf",
            pages=[
                DocumentPageResult(
                    page_number=1,
                    text=(
                        "Documento con texto nativo "
                        "suficiente para la prueba"
                    ),
                    text_source=(
                        TEXT_SOURCE_NATIVE
                    ),
                    confidence=1.0,
                    requires_ocr=False,
                    metadata={
                        "test": True,
                    },
                )
            ],
            warnings=[
                "aviso de prueba"
            ],
            metadata={
                "source": "unit-test",
            },
        )

    def test_persists_and_restores_result(self):
        result = self._native_result()

        saved = (
            document_ocr_repository
            .persist_result(
                result,
                pipeline_version="V1",
                native_extractor="PYPDF",
                ocr_engine="FAKE",
                ocr_engine_version="1",
                ocr_language="eng",
                render_dpi=220,
                policy_fingerprint="policy",
                db_path=self.db_path,
            )
        )

        self.assertEqual(
            saved.status,
            STATUS_NATIVE_TEXT,
        )
        self.assertEqual(
            saved.page_count,
            1,
        )
        self.assertEqual(
            saved.pages[0].text,
            result.pages[0].text,
        )
        self.assertTrue(
            saved.metadata["cache"][
                "cache_hit"
            ]
        )

    def test_upsert_does_not_duplicate_run(self):
        result = self._native_result()

        for _ in range(2):
            (
                document_ocr_repository
                .persist_result(
                    result,
                    pipeline_version="V1",
                    native_extractor="PYPDF",
                    ocr_engine="FAKE",
                    ocr_engine_version="1",
                    ocr_language="eng",
                    render_dpi=220,
                    policy_fingerprint="policy",
                    db_path=self.db_path,
                )
            )

        conn = sqlite3.connect(
            self.db_path
        )

        run_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM document_intelligence_runs
            """
        ).fetchone()[0]

        page_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM document_intelligence_pages
            """
        ).fetchone()[0]

        conn.close()

        self.assertEqual(
            run_count,
            1,
        )
        self.assertEqual(
            page_count,
            1,
        )

    def test_cache_key_changes_with_language(self):
        result = self._native_result()

        for language in (
            "eng",
            "spa",
        ):
            (
                document_ocr_repository
                .persist_result(
                    result,
                    pipeline_version="V1",
                    native_extractor="PYPDF",
                    ocr_engine="FAKE",
                    ocr_engine_version="1",
                    ocr_language=language,
                    render_dpi=220,
                    policy_fingerprint="policy",
                    db_path=self.db_path,
                )
            )

        conn = sqlite3.connect(
            self.db_path
        )

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM document_intelligence_runs
            """
        ).fetchone()[0]

        conn.close()

        self.assertEqual(
            count,
            2,
        )

    def test_process_document_uses_cache(self):
        engine = FakeEngine()
        native_result = self._native_result()

        with patch.object(
            document_intelligence_service,
            "extract_document_text",
            return_value=native_result,
        ) as extractor:
            first = process_document(
                self.document_path,
                engine=engine,
                language="eng",
                db_path=self.db_path,
            )

            second = process_document(
                self.document_path,
                engine=engine,
                language="eng",
                db_path=self.db_path,
            )

        self.assertEqual(
            extractor.call_count,
            1,
        )
        self.assertFalse(
            first.metadata["cache"][
                "cache_hit"
            ]
        )
        self.assertTrue(
            second.metadata["cache"][
                "cache_hit"
            ]
        )

    def test_ocr_pipeline_removes_rendered_files(
        self,
    ):
        from backend.services.document_intelligence import (
            TEXT_SOURCE_NONE,
            STATUS_OCR_REQUIRED,
        )

        pending_result = DocumentTextResult(
            status=STATUS_OCR_REQUIRED,
            source_path=str(
                self.document_path
            ),
            source_name="document.pdf",
            source_suffix=".pdf",
            sha256=(
                document_intelligence_service
                .calculate_sha256(
                    self.document_path
                )
            ),
            mime_type="application/pdf",
            pages=[
                DocumentPageResult(
                    page_number=1,
                    text="",
                    text_source=(
                        TEXT_SOURCE_NONE
                    ),
                    confidence=0.0,
                    requires_ocr=True,
                )
            ],
        )

        created_directories = []

        class TemporaryRenderer:
            def __init__(
                self,
                *,
                dpi,
                output_directory,
            ):
                self.dpi = dpi
                self.output_directory = Path(
                    output_directory
                )
                created_directories.append(
                    self.output_directory
                )

        def fake_complete(
            document_result,
            *,
            engine,
            renderer,
            language,
            policy,
        ):
            image_path = (
                renderer.output_directory
                / "page_1.png"
            )
            image_path.write_bytes(
                b"temporary-image"
            )

            return self._native_result()

        engine = FakeEngine()

        with patch.object(
            document_intelligence_service,
            "extract_document_text",
            return_value=pending_result,
        ), patch.object(
            document_intelligence_service,
            "PdfPageRenderer",
            TemporaryRenderer,
        ), patch.object(
            document_intelligence_service,
            "complete_document_ocr",
            side_effect=fake_complete,
        ):
            result = process_document(
                self.document_path,
                engine=engine,
                language="eng",
                db_path=self.db_path,
                force_reprocess=True,
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

    def test_force_reprocess_bypasses_cache(self):
        engine = FakeEngine()
        native_result = self._native_result()

        with patch.object(
            document_intelligence_service,
            "extract_document_text",
            return_value=native_result,
        ) as extractor:
            process_document(
                self.document_path,
                engine=engine,
                language="eng",
                db_path=self.db_path,
            )

            process_document(
                self.document_path,
                engine=engine,
                language="eng",
                db_path=self.db_path,
                force_reprocess=True,
            )

        self.assertEqual(
            extractor.call_count,
            2,
        )


if __name__ == "__main__":
    unittest.main()
