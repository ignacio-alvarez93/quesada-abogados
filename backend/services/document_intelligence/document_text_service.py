"""
Extracción documental normalizada.

Fase inicial:
- soporta PDF;
- extrae texto nativo por página con pypdf;
- calcula SHA256;
- aplica una política común de suficiencia;
- marca páginas que deben pasar por OCR;
- todavía no ejecuta ningún motor OCR.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

from .document_page_result import (
    DocumentPageResult,
    TEXT_SOURCE_NATIVE,
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
    STATUS_UNSUPPORTED,
)


SUPPORTED_SUFFIXES = {
    ".pdf": "application/pdf",
}


def calculate_sha256(
    source_path: str | Path,
) -> str:
    path = Path(source_path)
    digest = hashlib.sha256()

    with path.open("rb") as file_handle:
        for chunk in iter(
            lambda: file_handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _require_existing_file(
    source_path: str | Path,
) -> Path:
    path = Path(source_path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el archivo: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"La ruta no es un archivo: {path}"
        )

    return path


def _document_status(
    pages: list[DocumentPageResult],
) -> str:
    if not pages:
        return STATUS_EMPTY_DOCUMENT

    native_count = sum(
        1
        for page in pages
        if page.text_source
        == TEXT_SOURCE_NATIVE
    )

    ocr_required_count = sum(
        1
        for page in pages
        if page.requires_ocr
    )

    if native_count == len(pages):
        return STATUS_NATIVE_TEXT

    if (
        native_count > 0
        and ocr_required_count > 0
    ):
        return STATUS_PARTIAL_OCR_REQUIRED

    return STATUS_OCR_REQUIRED


def extract_pdf_native_text(
    source_path: str | Path,
    *,
    policy: DocumentTextPolicy = (
        DEFAULT_TEXT_POLICY
    ),
) -> DocumentTextResult:
    path = _require_existing_file(
        source_path
    )

    if path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Formato no soportado: {path.suffix}"
        )

    if PdfReader is None:
        raise RuntimeError(
            "No está disponible pypdf"
        )

    reader = PdfReader(
        str(path)
    )

    if reader.is_encrypted:
        raise ValueError(
            "El PDF está cifrado y no "
            "puede analizarse"
        )

    pages = []
    global_warnings = []

    for page_number, page in enumerate(
        reader.pages,
        start=1,
    ):
        raw_text = str(
            page.extract_text() or ""
        ).strip()

        assessment = policy.analyze(
            raw_text
        )

        sufficient = bool(
            assessment["sufficient"]
        )

        page_warnings = []

        if not sufficient:
            page_warnings.extend(
                assessment["reasons"]
            )
            page_warnings.append(
                "La página requiere OCR"
            )

        pages.append(
            DocumentPageResult(
                page_number=page_number,
                text=raw_text,
                text_source=(
                    TEXT_SOURCE_NATIVE
                    if sufficient
                    else TEXT_SOURCE_NONE
                ),
                confidence=(
                    1.0
                    if sufficient
                    else 0.0
                ),
                requires_ocr=(
                    not sufficient
                ),
                warnings=page_warnings,
                metadata={
                    "native_text_assessment": (
                        assessment
                    ),
                },
            )
        )

    status = _document_status(
        pages
    )

    if status == STATUS_OCR_REQUIRED:
        global_warnings.append(
            "El documento completo requiere OCR"
        )
    elif (
        status
        == STATUS_PARTIAL_OCR_REQUIRED
    ):
        global_warnings.append(
            "Algunas páginas requieren OCR"
        )

    return DocumentTextResult(
        status=status,
        source_path=str(path),
        source_name=path.name,
        source_suffix=path.suffix.lower(),
        sha256=calculate_sha256(path),
        mime_type="application/pdf",
        pages=pages,
        warnings=global_warnings,
        metadata={
            "native_extractor": "pypdf",
            "policy": {
                "minimum_characters": (
                    policy.minimum_characters
                ),
                (
                    "minimum_alphanumeric_"
                    "characters"
                ): (
                    policy
                    .minimum_alphanumeric_characters
                ),
                "minimum_words": (
                    policy.minimum_words
                ),
            },
        },
    )


def extract_document_text(
    source_path: str | Path,
    *,
    policy: DocumentTextPolicy = (
        DEFAULT_TEXT_POLICY
    ),
) -> DocumentTextResult:
    path = _require_existing_file(
        source_path
    )
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return extract_pdf_native_text(
            path,
            policy=policy,
        )

    return DocumentTextResult(
        status=STATUS_UNSUPPORTED,
        source_path=str(path),
        source_name=path.name,
        source_suffix=suffix,
        sha256=calculate_sha256(path),
        mime_type="",
        pages=[],
        warnings=[
            (
                "Formato no soportado por la "
                "extracción documental actual"
            )
        ],
        metadata={
            "supported_suffixes": sorted(
                SUPPORTED_SUFFIXES
            ),
        },
    )
