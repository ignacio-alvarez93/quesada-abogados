from __future__ import annotations

from pathlib import Path

from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.image_tools_service import get_image_metadata
from backend.services.document_tools.pdf_tools_service import get_pdf_metadata
from backend.services.document_tools.safe_file_service import assert_existing_file, file_metadata


PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
WORD_SUFFIXES = {".doc", ".docx"}
EXCEL_SUFFIXES = {".xls", ".xlsx", ".csv"}


def get_document_metadata(source_path: str | Path) -> DocumentToolResult:
    operation = "document_metadata"

    try:
        source = assert_existing_file(source_path)
        suffix = source.suffix.lower()

        if suffix in PDF_SUFFIXES:
            return get_pdf_metadata(source)

        if suffix in IMAGE_SUFFIXES:
            return get_image_metadata(source)

        metadata = file_metadata(source)
        metadata.update(
            {
                "mime_type": None,
                "category": _guess_category(suffix),
                "supported_for_deep_metadata": False,
            }
        )

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=source,
            metadata=metadata,
            warnings=["Metadatos profundos no implementados todavía para este formato."],
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def _guess_category(suffix: str) -> str:
    if suffix in WORD_SUFFIXES:
        return "word"

    if suffix in EXCEL_SUFFIXES:
        return "spreadsheet"

    if suffix in PDF_SUFFIXES:
        return "pdf"

    if suffix in IMAGE_SUFFIXES:
        return "image"

    return "other"
