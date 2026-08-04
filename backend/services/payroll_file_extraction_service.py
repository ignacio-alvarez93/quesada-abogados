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


def extract_pdf_pages_text(path):
    """
    Extrae texto de un PDF conservando la página de origen.

    La numeración de páginas empieza en 1.
    """
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

    for page_number, page in enumerate(
        reader.pages,
        start=1,
    ):
        text = str(
            page.extract_text() or ""
        ).strip()

        pages.append(
            {
                "page_number": page_number,
                "text": text,
                "has_text": bool(text),
                "text_length": len(text),
            }
        )

    return pages


def _looks_like_payroll_text(text):
    normalized = str(text or "").upper()

    indicators = [
        "NÓMINA",
        "NOMINA",
        "RECIBO DE SALARIOS",
        "TOTAL DEVENGADO",
        "TOTAL DEDUCCIONES",
        "LÍQUIDO A PERCIBIR",
        "LIQUIDO A PERCIBIR",
    ]

    matches = sum(
        1
        for indicator in indicators
        if indicator in normalized
    )

    return matches >= 2


def _period_key(extraction):
    month = extraction.get("period_month")
    year = extraction.get("period_year")

    if month and year:
        return f"{int(year):04d}-{int(month):02d}"

    return ""


def extract_payroll_bundle(path):
    """
    Analiza un PDF que puede contener varias nóminas.

    MVP:
    - cada página con suficientes indicadores se trata como
      una posible nómina;
    - conserva página, secuencia y periodo;
    - no persiste ni aplica ingresos;
    - las páginas ambiguas quedan pendientes de revisión.

    La agrupación de una nómina distribuida en varias páginas
    se incorporará en una fase posterior.
    """
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
            "payroll_count": 0,
            "payrolls": [],
            "unclassified_pages": [],
            "warnings": [
                (
                    "El formato todavía no está "
                    "soportado por este adaptador."
                )
            ],
        }

    pages = extract_pdf_pages_text(path)
    digest = _calculate_sha256(path)

    pages_with_text = [
        page
        for page in pages
        if page["has_text"]
    ]

    if not pages_with_text:
        return {
            "status": STATUS_OCR_REQUIRED,
            "source_path": str(path),
            "source_name": path.name,
            "source_suffix": suffix,
            "sha256": digest,
            "page_count": len(pages),
            "pages_with_text": 0,
            "requires_ocr": True,
            "requires_manual_review": True,
            "payroll_count": 0,
            "payrolls": [],
            "unclassified_pages": [
                page["page_number"]
                for page in pages
            ],
            "warnings": [
                (
                    "El PDF no contiene texto "
                    "extraíble. Será necesario OCR."
                )
            ],
        }

    payrolls = []
    unclassified_pages = []

    for page in pages:
        page_number = page["page_number"]
        page_text = page["text"]

        if not page_text:
            unclassified_pages.append(page_number)
            continue

        if not _looks_like_payroll_text(page_text):
            unclassified_pages.append(page_number)
            continue

        extraction = (
            payroll_parser.extract_payroll_text(
                page_text,
                source_path=path,
            )
        )

        extraction.update(
            {
                "sequence": len(payrolls) + 1,
                "source_pages": [page_number],
                "source_page_start": page_number,
                "source_page_end": page_number,
                "period_key": _period_key(
                    extraction
                ),
                "requires_manual_review": True,
            }
        )

        payrolls.append(extraction)

    warnings = []

    if unclassified_pages:
        warnings.append(
            (
                "Hay páginas sin clasificar que "
                "requieren revisión manual: "
                + ", ".join(
                    str(number)
                    for number in unclassified_pages
                )
            )
        )

    period_keys = [
        payroll["period_key"]
        for payroll in payrolls
        if payroll["period_key"]
    ]

    duplicated_periods = sorted(
        {
            period
            for period in period_keys
            if period_keys.count(period) > 1
        }
    )

    if duplicated_periods:
        warnings.append(
            (
                "Se han detectado periodos repetidos: "
                + ", ".join(duplicated_periods)
            )
        )

    return {
        "status": (
            STATUS_EXTRACTED
            if payrolls
            else STATUS_OCR_REQUIRED
        ),
        "source_path": str(path),
        "source_name": path.name,
        "source_suffix": suffix,
        "sha256": digest,
        "page_count": len(pages),
        "pages_with_text": len(pages_with_text),
        "requires_ocr": not bool(payrolls),
        "requires_manual_review": True,
        "payroll_count": len(payrolls),
        "payrolls": payrolls,
        "unclassified_pages": unclassified_pages,
        "warnings": warnings,
    }
