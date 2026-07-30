from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


SUPPORTED_EXTENSIONS = {".pdf"}


def _compact_spaces(value: str) -> str:
    return re.sub(
        r"[ \t]+",
        " ",
        str(value or ""),
    ).strip()


def _normalize_search_text(value: str) -> str:
    """
    Normaliza el texto extraído por pypdf.

    Algunos documentos oficiales:
    - separan etiquetas y valores en líneas distintas;
    - alteran el orden visual de algunas columnas;
    - devuelven ligaduras Unicode;
    - insertan saltos y tabulaciones.
    """
    text = str(value or "")

    replacements = {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "\u00ad": "",
        "\xa0": " ",
    }

    for source, target in replacements.items():
        text = text.replace(source, target)

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()



def _first_match(
    patterns,
    text: str,
    flags: int = re.IGNORECASE | re.MULTILINE,
) -> str:
    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags,
        )
        if match:
            return str(
                match.group(1) or ""
            ).strip()

    return ""


def _normalize_datetime(value: str) -> str:
    raw = str(value or "").strip()

    if not raw:
        return ""

    for fmt in (
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(
                raw,
                fmt,
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except ValueError:
            pass

    return raw


def _normalize_date(value: str) -> str:
    raw = str(value or "").strip()

    if not raw:
        return ""

    for fmt in (
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(
                raw,
                fmt,
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return raw


def calculate_sha256(path) -> str:
    path = Path(path)
    digest = hashlib.sha256()

    with path.open("rb") as source:
        for chunk in iter(
            lambda: source.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def extract_pdf_text(path) -> str:
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el PDF: {path}"
        )

    if path.suffix.lower() not in (
        SUPPORTED_EXTENSIONS
    ):
        raise ValueError(
            "El resguardo DEHú debe ser un PDF"
        )

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "No está disponible pypdf"
        ) from exc

    reader = PdfReader(str(path))

    if reader.is_encrypted:
        raise ValueError(
            "El PDF está cifrado"
        )

    pages = []

    for page in reader.pages:
        pages.append(
            page.extract_text() or ""
        )

    text = "\n".join(pages).strip()

    if not text:
        raise ValueError(
            "El PDF no contiene texto extraíble"
        )

    return text


def extract_dehu_receipt_text(
    text: str,
) -> Dict[str, Any]:
    raw_text = str(text or "")

    normalized = _compact_spaces(
        raw_text
    )

    search_text = _normalize_search_text(
        raw_text
    )

    normalized_upper = (
        search_text.upper()
    )

    is_dehu = (
        "DIRECCIÓN ELECTRÓNICA HABILITADA"
        in normalized_upper
        or
        "DIRECCION ELECTRONICA HABILITADA"
        in normalized_upper
        or
        "EL SERVICIO DE DIRECCIÓN ELECTRÓNICA"
        in normalized_upper
        or
        "EL SERVICIO DE DIRECCION ELECTRONICA"
        in normalized_upper
    )

    application = _first_match(
        [
            r"\bAplicaci[oó]n\s+"
            r"C[oó]digo\s+CSV.*?\n"
            r"\s*([A-Z]{2,20})\s+",
            r"\bAplicaci[oó]n\s*[:\-]?\s*"
            r"([A-Z]{2,20})\b",
        ],
        raw_text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    ).upper()

    csv_value = _first_match(
        [
            r"\b(DEHU-(?:[0-9A-Za-z]+-){5,}"
            r"[0-9A-Za-z]+)\b",
            r"\bC[oó]digo\s+CSV\s*[:\-]?\s*"
            r"(DEHU-[0-9A-Za-z-]+)",
        ],
        raw_text,
    )

    registration_date = _first_match(
        [
            r"\bFecha\s+de\s+registro\s*"
            r"[:\-]?\s*"
            r"(\d{2}/\d{2}/\d{4})",
            r"\b"
            r"(?:DEHU-[0-9A-Za-z-]+)"
            r"\s+"
            r"(\d{2}/\d{2}/\d{4})",
        ],
        raw_text,
    )

    validation_url = _first_match(
        [
            r"\bURL\s+de\s+validaci[oó]n.*?"
            r"(https?://[^\s]+)",
            r"\b(https://run\.gob\.es/[^\s]+)",
        ],
        raw_text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    associated_document = _first_match(
        [
            r"\bDocumento\s+asociado\s*:"
            r"\s*([A-Z0-9\-]+)",
            r"\bDNI/NIE\s+del\s+interesado.*?"
            r"\b([XYZ]?\d{7,8}[A-Z])\b",
        ],
        raw_text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    ).upper()

    interested_party_name = _first_match(
        [
            r"\bNombre/Raz[oó]n\s+social\s*:"
            r"\s*([^\n\r]+)",
        ],
        raw_text,
    )

    relationship_role = _first_match(
        [
            r"\bEn\s+calidad\s+de\s+"
            r"([A-ZÁÉÍÓÚÜÑ ]+?)"
            r"\s+para\s+",
        ],
        raw_text,
    ).upper()

    action = _first_match(
        [
            r"\bpara\s+"
            r"(ACEPTAR|RECHAZAR)"
            r"\s+la\s+notificaci[oó]n",

            r"\b(ACEPTAR|RECHAZAR)"
            r"\s+(?:el\s+contenido\s+de\s+)?"
            r"la\s+notificaci[oó]n",

            r"\bActuaci[oó]n\s*[:\-]?\s*"
            r"(ACEPTAR|RECHAZAR)\b",
        ],
        search_text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    ).upper()

    dehu_identifier = _first_match(
        [
            r"\bIdentificador\s*[:\-]?\s*"
            r"([0-9a-fA-F]{16,64})\b",

            # El valor puede aparecer antes de la etiqueta
            # cuando pypdf altera el orden visual.
            r"\b([0-9a-fA-F]{16,64})\b"
            r"(?=.{0,120}\bIdentificador\b)",
        ],
        search_text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    ).lower()


    issuer = _first_match(
        [
            r"\bRemitida\s+por\s*:"
            r"\s*([^\n\r]+)",
        ],
        raw_text,
    )

    concept = _first_match(
        [
            r"\bConcepto\s*:"
            r"\s*(not_[0-9A-Za-z_-]+)",
            r"\bConcepto\s*:"
            r"\s*([^\n\r]+)",
        ],
        raw_text,
    )

    reference_value = _first_match(
        [
            r"\bnot_(\d{12,20})"
            r"(?:_[0-9A-Za-z]+)+\b",
        ],
        concept or raw_text,
    )

    available_at = _first_match(
        [
            r"\bFecha\s+de\s+puesta\s+a\s+"
            r"disposici[oó]n\s*:"
            r"\s*"
            r"(\d{2}/\d{2}/\d{4}"
            r"\s+\d{2}:\d{2}(?::\d{2})?)",
        ],
        raw_text,
    )

    accessed_at = _first_match(
        [
            r"\bFecha\s+de\s+acceso\s+al\s+"
            r"contenido\s+de\s+la\s+"
            r"notificaci[oó]n\s*[:\-]?\s*"
            r"(\d{2}/\d{2}/\d{4}"
            r"\s+\d{2}:\d{2}(?::\d{2})?)",

            r"\bFecha\s+de\s+acceso"
            r".{0,180}?"
            r"(\d{2}/\d{2}/\d{4}"
            r"\s+\d{2}:\d{2}(?::\d{2})?)",

            # Fallback: pypdf puede extraer primero
            # el valor y después la etiqueta.
            r"(\d{2}/\d{2}/\d{4}"
            r"\s+\d{2}:\d{2}(?::\d{2})?)"
            r"(?=.{0,180}?"
            r"Fecha\s+de\s+acceso)",
        ],
        search_text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )


    required = {
        "dehu_identifier":
            "No se detectó el identificador DEHú",
        "concept":
            "No se detectó el concepto DEHú",
        "accessed_at":
            "No se detectó la fecha de acceso",
    }

    result = {
        "document_type":
            "DEHU_ACCESS_RECEIPT",
        "format":
            (
                "DEHU_ACCESS_RECEIPT"
                if is_dehu
                else "UNKNOWN"
            ),
        "application":
            application or "DEHU",
        "registration_csv":
            csv_value,
        "registration_date":
            _normalize_date(
                registration_date
            ),
        "validation_url":
            validation_url,
        "interested_party_document":
            associated_document,
        "interested_party_name":
            interested_party_name,
        "relationship_role":
            relationship_role,
        "action":
            action,
        "dehu_identifier":
            dehu_identifier,
        "issuer":
            issuer,
        "concept":
            concept,
        "reference_value":
            reference_value,
        "available_at":
            _normalize_datetime(
                available_at
            ),
        "accessed_at":
            _normalize_datetime(
                accessed_at
            ),
    }

    warnings = [
        message
        for key, message in required.items()
        if not result.get(key)
    ]

    if not is_dehu:
        warnings.append(
            "El documento no se reconoce "
            "como resguardo DEHú"
        )

    confidence_fields = (
        "dehu_identifier",
        "concept",
        "reference_value",
        "issuer",
        "accessed_at",
        "registration_csv",
    )

    detected = sum(
        bool(result.get(key))
        for key in confidence_fields
    )

    result["warnings"] = warnings
    result["confidence"] = round(
        detected
        / len(confidence_fields),
        2,
    )

    return result


def extract_dehu_receipt(
    path,
) -> Dict[str, Any]:
    path = Path(path)

    text = extract_pdf_text(path)

    result = extract_dehu_receipt_text(
        text
    )

    result["sha256"] = calculate_sha256(
        path
    )
    result["source_path"] = str(path)
    result["source_name"] = path.name

    return result
