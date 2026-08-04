"""
Infraestructura transversal de inteligencia documental.
"""

from .document_page_result import (
    DocumentPageResult,
    TEXT_SOURCE_NATIVE,
    TEXT_SOURCE_OCR,
    TEXT_SOURCE_NONE,
)
from .document_text_policy import (
    DocumentTextPolicy,
    DEFAULT_TEXT_POLICY,
)
from .document_text_result import (
    DocumentTextResult,
    STATUS_NATIVE_TEXT,
    STATUS_PARTIAL_OCR_REQUIRED,
    STATUS_OCR_REQUIRED,
    STATUS_EMPTY_DOCUMENT,
    STATUS_UNSUPPORTED,
    STATUS_ERROR,
)
from .document_text_service import (
    calculate_sha256,
    extract_document_text,
    extract_pdf_native_text,
)


__all__ = [
    "DocumentPageResult",
    "DocumentTextPolicy",
    "DocumentTextResult",
    "DEFAULT_TEXT_POLICY",
    "TEXT_SOURCE_NATIVE",
    "TEXT_SOURCE_OCR",
    "TEXT_SOURCE_NONE",
    "STATUS_NATIVE_TEXT",
    "STATUS_PARTIAL_OCR_REQUIRED",
    "STATUS_OCR_REQUIRED",
    "STATUS_EMPTY_DOCUMENT",
    "STATUS_UNSUPPORTED",
    "STATUS_ERROR",
    "calculate_sha256",
    "extract_document_text",
    "extract_pdf_native_text",
]

from .ocr_engine import (
    OcrEngine,
    OcrEngineResult,
)
from .tesseract_cli_ocr_engine import (
    TesseractCliOcrEngine,
)
from .document_image_renderer import (
    PdfPageRenderer,
    RenderedDocumentPage,
)
from .document_ocr_service import (
    complete_document_ocr,
)

__all__.extend(
    [
        "OcrEngine",
        "OcrEngineResult",
        "TesseractCliOcrEngine",
        "PdfPageRenderer",
        "RenderedDocumentPage",
        "complete_document_ocr",
    ]
)
