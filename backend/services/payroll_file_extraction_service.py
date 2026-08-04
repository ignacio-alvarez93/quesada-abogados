"""
Adaptador de archivos para extracción de nóminas.

Fase actual:
- soporta PDF con capa de texto;
- no realiza OCR;
- detecta cuándo sería necesario OCR;
- delega el análisis semántico al parser puro.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from backend.services import (
    payroll_document_extraction_service
    as payroll_parser,
)


STATUS_EXTRACTED = "EXTRACTED"
STATUS_OCR_REQUIRED = "OCR_REQUIRED"
STATUS_UNSUPPORTED = "UNSUPPORTED"

SUPPORTED_PDF_SUFFIXES = {".pdf"}


def _calculate_sha256(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as file_handle:
        for chunk in iter(
            lambda: file_handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def extract_pdf_text(path):
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el archivo: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"La ruta no es un archivo: {path}"
        )

    if path.suffix.lower() not in SUPPORTED_PDF_SUFFIXES:
        raise ValueError(
            f"Formato no soportado: {path.suffix}"
        )

    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError(
            "No está disponible pypdf"
        ) from exc

    reader = PdfReader(str(path))

    if reader.is_encrypted:
        raise ValueError(
            "El PDF está cifrado y no puede analizarse"
        )

    pages = []
    pages_with_text = 0

    for page in reader.pages:
        page_text = page.extract_text() or ""
        page_text = str(page_text).strip()

        if page_text:
            pages_with_text += 1

        pages.append(page_text)

    text = "\n\n".join(pages).strip()

    return {
        "text": text,
        "page_count": len(reader.pages),
        "pages_with_text": pages_with_text,
    }


def extract_payroll_file(path):
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el archivo: {path}"
        )

    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_PDF_SUFFIXES:
        return {
            "status": STATUS_UNSUPPORTED,
            "source_path": str(path),
            "source_name": path.name,
            "source_suffix": suffix,
            "requires_ocr": False,
            "requires_manual_review": True,
            "warnings": [
                (
                    "El formato todavía no está "
                    "soportado por este adaptador."
                )
            ],
        }

    extracted = extract_pdf_text(path)
    text = extracted["text"]

    if not text:
        return {
            "status": STATUS_OCR_REQUIRED,
            "source_path": str(path),
            "source_name": path.name,
            "source_suffix": suffix,
            "sha256": _calculate_sha256(path),
            "page_count": extracted["page_count"],
            "pages_with_text": 0,
            "requires_ocr": True,
            "requires_manual_review": True,
            "warnings": [
                (
                    "El PDF no contiene texto "
                    "extraíble. Será necesario OCR."
                )
            ],
        }

    result = payroll_parser.extract_payroll_text(
        text,
        source_path=path,
    )

    result.update(
        {
            "status": STATUS_EXTRACTED,
            "source_name": path.name,
            "source_suffix": suffix,
            "sha256": _calculate_sha256(path),
            "page_count": extracted["page_count"],
            "pages_with_text": (
                extracted["pages_with_text"]
            ),
            "requires_ocr": False,
        }
    )

    return result
