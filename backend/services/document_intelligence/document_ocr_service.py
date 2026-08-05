"""
Orquestación OCR transversal.

Completa únicamente las páginas marcadas como requires_ocr.
No interpreta el tipo documental ni aplica datos a expedientes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .document_image_renderer import (
    PdfPageRenderer,
)
from .document_page_result import (
    DocumentPageResult,
    TEXT_SOURCE_NATIVE,
    TEXT_SOURCE_OCR,
    TEXT_SOURCE_NONE,
)
from .document_text_policy import (
    DEFAULT_TEXT_POLICY,
    DocumentTextPolicy,
)
from .document_text_result import (
    DocumentTextResult,
    STATUS_NATIVE_TEXT,
    STATUS_PARTIAL_OCR_REQUIRED,
    STATUS_OCR_REQUIRED,
    STATUS_EMPTY_DOCUMENT,
)
from .ocr_engine import OcrEngine


def _recalculate_status(
    pages: list[DocumentPageResult],
) -> str:
    if not pages:
        return STATUS_EMPTY_DOCUMENT

    unresolved = [
        page
        for page in pages
        if page.requires_ocr
    ]

    if not unresolved:
        return STATUS_NATIVE_TEXT

    resolved_count = sum(
        1
        for page in pages
        if page.text_source in {
            TEXT_SOURCE_NATIVE,
            TEXT_SOURCE_OCR,
        }
    )

    if resolved_count:
        return STATUS_PARTIAL_OCR_REQUIRED

    return STATUS_OCR_REQUIRED


def complete_document_ocr(
    document_result: DocumentTextResult,
    *,
    engine: OcrEngine,
    renderer: PdfPageRenderer | None = None,
    language: str = "eng",
    policy: DocumentTextPolicy = DEFAULT_TEXT_POLICY,
) -> DocumentTextResult:
    if not isinstance(
        document_result,
        DocumentTextResult,
    ):
        raise TypeError(
            "document_result debe ser "
            "DocumentTextResult"
        )

    if not engine.is_available():
        raise RuntimeError(
            "El motor OCR no está disponible"
        )

    pages_to_process = (
        document_result.pages_requiring_ocr
    )

    if not pages_to_process:
        return document_result

    if (
        document_result.source_suffix.lower()
        != ".pdf"
    ):
        raise ValueError(
            "Esta fase OCR solo admite PDF"
        )

    if renderer is None:
        with tempfile.TemporaryDirectory(
            prefix="quesada_ocr_"
        ) as temporary_directory:
            return complete_document_ocr(
                document_result,
                engine=engine,
                renderer=PdfPageRenderer(
                    output_directory=(
                        temporary_directory
                    )
                ),
                language=language,
                policy=policy,
            )

    rendered_pages = renderer.render_pages(
        document_result.source_path,
        pages_to_process,
    )

    rendered_by_page = {
        item.page_number: item
        for item in rendered_pages
    }

    resulting_pages = []
    global_warnings = list(
        document_result.warnings
    )

    for original_page in document_result.pages:
        if not original_page.requires_ocr:
            resulting_pages.append(
                original_page
            )
            continue

        rendered = rendered_by_page.get(
            original_page.page_number
        )

        if not rendered:
            resulting_pages.append(
                original_page
            )
            global_warnings.append(
                "No se renderizó la página "
                f"{original_page.page_number}"
            )
            continue

        ocr_result = engine.extract_image_text(
            rendered.image_path,
            language=language,
        )

        assessment = policy.analyze(
            ocr_result.text
        )
        sufficient = bool(
            assessment["sufficient"]
        )

        warnings = [
            *original_page.warnings,
            *ocr_result.warnings,
        ]

        if not sufficient:
            warnings.extend(
                assessment["reasons"]
            )
            warnings.append(
                "El OCR no produjo texto suficiente"
            )

        resulting_pages.append(
            DocumentPageResult(
                page_number=(
                    original_page.page_number
                ),
                text=ocr_result.text,
                text_source=(
                    TEXT_SOURCE_OCR
                    if sufficient
                    else TEXT_SOURCE_NONE
                ),
                confidence=(
                    ocr_result.confidence
                    if sufficient
                    else 0.0
                ),
                requires_ocr=(
                    not sufficient
                ),
                rotation=(
                    original_page.rotation
                ),
                language=(
                    ocr_result.language
                ),
                warnings=warnings,
                metadata={
                    **original_page.metadata,
                    "ocr": ocr_result.to_dict(),
                    "render": (
                        rendered.to_dict()
                    ),
                    "ocr_text_assessment": (
                        assessment
                    ),
                },
            )
        )

    status = _recalculate_status(
        resulting_pages
    )

    if (
        status
        == STATUS_PARTIAL_OCR_REQUIRED
    ):
        global_warnings.append(
            "Persisten páginas pendientes "
            "después del OCR"
        )
    elif status == STATUS_OCR_REQUIRED:
        global_warnings.append(
            "El OCR no resolvió el documento"
        )

    return DocumentTextResult(
        status=status,
        source_path=document_result.source_path,
        source_name=document_result.source_name,
        source_suffix=document_result.source_suffix,
        sha256=document_result.sha256,
        mime_type=document_result.mime_type,
        pages=resulting_pages,
        warnings=list(
            dict.fromkeys(global_warnings)
        ),
        errors=list(document_result.errors),
        metadata={
            **document_result.metadata,
            "ocr_engine": engine.engine_code,
            "ocr_engine_version": (
                engine.get_version()
            ),
            "ocr_language": language,
            "ocr_requested_pages": (
                pages_to_process
            ),
            "ocr_completed_pages": [
                page.page_number
                for page in resulting_pages
                if (
                    page.text_source
                    == TEXT_SOURCE_OCR
                )
            ],
        },
    )
