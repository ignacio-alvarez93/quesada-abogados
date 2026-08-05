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
from backend.services.document_intelligence import (
    DocumentTextResult,
    TesseractCliOcrEngine,
)
from backend.services.document_intelligence import (
    document_intelligence_service,
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
    normalized = (
        payroll_parser
        ._normalized_text(text)
    )

    indicator_groups = [
        [
            "NOMINA",
            "RECIBO DE SALARIOS",
            "PERIODO DE LIQUIDACION",
        ],
        [
            "TOTAL DEVENGADO",
            "TOTAL DEVENGOS",
        ],
        [
            "TOTAL DEDUCCIONES",
            "TOTAL A DEDUCIR",
            "TOTAL APORTACIONES",
        ],
        [
            "LIQUIDO A PERCIBIR",
            "LIQUIDO TOTAL A PERCIBIR",
            "NETO A PERCIBIR",
        ],
        [
            "BASE DE COTIZACION",
            "CONTINGENCIAS COMUNES",
        ],
    ]

    matches = sum(
        1
        for alternatives in indicator_groups
        if any(
            indicator in normalized
            for indicator in alternatives
        )
    )

    return matches >= 2


def _period_key(extraction):
    month = extraction.get("period_month")
    year = extraction.get("period_year")

    if month and year:
        return f"{int(year):04d}-{int(month):02d}"

    return ""


def extract_payroll_bundle_from_document_result(
    document_result,
):
    """
    Adapta un resultado documental normalizado al contrato
    de múltiples propuestas de nómina.

    No abre archivos, no ejecuta OCR, no persiste datos y
    no modifica ningún expediente.
    """
    if not isinstance(
        document_result,
        DocumentTextResult,
    ):
        raise TypeError(
            "document_result debe ser "
            "DocumentTextResult"
        )

    payrolls = []
    unclassified_pages = []

    for page in document_result.pages:
        page_number = page.page_number
        page_text = str(
            page.text or ""
        ).strip()

        if (
            not page_text
            or not _looks_like_payroll_text(
                page_text
            )
        ):
            unclassified_pages.append(
                page_number
            )
            continue

        extraction = (
            payroll_parser.extract_payroll_text(
                page_text,
                source_path=(
                    document_result.source_path
                ),
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
                "document_text_source": (
                    page.text_source
                ),
                "document_text_confidence": (
                    page.confidence
                ),
                "document_language": (
                    page.language
                ),
            }
        )

        payrolls.append(extraction)

    document_warnings = list(
        document_result.warnings
    )

    if (
        not document_result.requires_ocr
        and document_result.ocr_text_pages
    ):
        obsolete_ocr_warnings = {
            "El documento completo requiere OCR",
            "El documento requiere OCR",
        }

        document_warnings = [
            warning
            for warning in document_warnings
            if warning
            not in obsolete_ocr_warnings
        ]

    warnings = [
        *document_warnings,
        *document_result.errors,
    ]

    if unclassified_pages:
        warnings.append(
            (
                "Hay páginas sin clasificar que "
                "requieren revisión manual: "
                + ", ".join(
                    str(number)
                    for number
                    in unclassified_pages
                )
            )
        )

    payrolls.sort(
        key=lambda payroll: (
            int(
                payroll.get("period_year")
                or 0
            ),
            int(
                payroll.get("period_month")
                or 0
            ),
            int(
                payroll.get(
                    "source_page_start"
                )
                or 0
            ),
        ),
        reverse=True,
    )

    for sequence, payroll in enumerate(
        payrolls,
        start=1,
    ):
        payroll["sequence"] = sequence

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

    warnings = list(
        dict.fromkeys(
            str(item)
            for item in warnings
            if str(item or "").strip()
        )
    )

    pages_with_text = sum(
        1
        for page in document_result.pages
        if page.has_text
    )

    return {
        "status": (
            STATUS_EXTRACTED
            if payrolls
            else STATUS_OCR_REQUIRED
        ),
        "source_path": (
            document_result.source_path
        ),
        "source_name": (
            document_result.source_name
        ),
        "source_suffix": (
            document_result.source_suffix
        ),
        "sha256": document_result.sha256,
        "page_count": (
            document_result.page_count
        ),
        "pages_with_text": pages_with_text,
        "native_text_pages": (
            document_result.native_text_pages
        ),
        "ocr_text_pages": (
            document_result.ocr_text_pages
        ),
        "requires_ocr": (
            document_result.requires_ocr
        ),
        "requires_manual_review": True,
        "payroll_count": len(payrolls),
        "payrolls": payrolls,
        "unclassified_pages": (
            unclassified_pages
        ),
        "warnings": warnings,
        "document_intelligence": {
            "status": document_result.status,
            "pages_requiring_ocr": (
                document_result
                .pages_requiring_ocr
            ),
            "metadata": dict(
                document_result.metadata
            ),
        },
    }


def extract_payroll_bundle(
    path,
    *,
    engine=None,
    language="spa",
    render_dpi=220,
    intelligence_db_path=None,
    force_reprocess=False,
):
    """
    Analiza un PDF que puede contener varias nóminas.

    La extracción técnica, el OCR y la caché se delegan en
    document_intelligence. El parser de nóminas solo recibe
    el texto normalizado de cada página.
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

    ocr_engine = (
        engine
        if engine is not None
        else TesseractCliOcrEngine()
    )

    process_kwargs = {
        "engine": ocr_engine,
        "language": language,
        "render_dpi": int(render_dpi),
        "force_reprocess": bool(
            force_reprocess
        ),
    }

    if intelligence_db_path is not None:
        process_kwargs["db_path"] = (
            intelligence_db_path
        )

    try:
        document_result = (
            document_intelligence_service
            .process_document(
                path,
                **process_kwargs,
            )
        )
    except RuntimeError as exc:
        message = str(exc)

        if (
            "motor OCR no está disponible"
            not in message.lower()
            and "tesseract" not in message.lower()
        ):
            raise

        document_result = (
            document_intelligence_service
            .extract_document_text(path)
        )

        document_result.warnings.append(
            "El motor OCR no está disponible; "
            "las páginas sin texto quedan pendientes."
        )

    return (
        extract_payroll_bundle_from_document_result(
            document_result
        )
    )
