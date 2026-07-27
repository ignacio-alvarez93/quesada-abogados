import hashlib
import re
from datetime import datetime
from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf"}


def _clean(value):
    return str(value or "").strip()


def _compact_spaces(value):
    return re.sub(
        r"\s+",
        " ",
        _clean(value),
    ).strip()


def _first_match(
    patterns,
    text,
    flags=re.IGNORECASE | re.MULTILINE,
):
    if isinstance(patterns, str):
        patterns = [patterns]

    for pattern in patterns:
        match = re.search(pattern, text, flags)

        if not match:
            continue

        value = (
            match.group(1)
            if match.lastindex
            else match.group(0)
        )

        value = _compact_spaces(value)

        if value:
            return value

    return ""


def _normalize_datetime(value):
    value = _clean(value)

    if not value:
        return ""

    for format_string in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(
                value,
                format_string,
            )

            if (
                "%H" in format_string
                or "%M" in format_string
            ):
                return parsed.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            return parsed.strftime("%Y-%m-%d")

        except ValueError:
            continue

    return ""


def _normalize_nie(value):
    value = re.sub(
        r"[^0-9A-Za-z]",
        "",
        _clean(value),
    ).upper()

    if re.fullmatch(
        r"[XYZ]\d{7}[A-Z]",
        value,
    ):
        return value

    return ""


def _normalize_expediente(value):
    value = re.sub(
        r"\D",
        "",
        _clean(value),
    )

    if 12 <= len(value) <= 20:
        return value

    return ""


def calculate_sha256(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as source:
        for chunk in iter(
            lambda: source.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def extract_pdf_text(path):
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"No existe el PDF: {path}"
        )

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            "El justificante de aportación debe ser un PDF"
        )

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "No está disponible pypdf"
        ) from exc

    reader = PdfReader(str(path))

    text = "\n".join(
        page.extract_text() or ""
        for page in reader.pages
    ).strip()

    if not text:
        raise ValueError(
            "El PDF no contiene texto extraíble"
        )

    return text


def extract_tax_submission_text(text):
    text = str(text or "")
    normalized_upper = _compact_spaces(text).upper()

    csv_value = _first_match(
        [
            r"\bC[ÓO]DIGO\s+SEGURO\s+DE\s+"
            r"VERIFICACI[ÓO]N\s*[:\-]\s*"
            r"([A-Z]{2,12}-[0-9A-Za-z-]{15,})",

            r"\bCSV\s*[:\-]\s*"
            r"([A-Z]{2,12}-[0-9A-Za-z-]{15,})",

            r"\b(GEISER-(?:[0-9A-Za-z]{4,}-){4,}"
            r"[0-9A-Za-z]{4,})\b",
        ],
        text,
    ).strip(".,;: ")

    # En algunos justificantes, pypdf invierte visualmente
    # el orden y devuelve:
    #
    # REGAGE26e00041927758Número de registro:
    #
    # Por eso no usamos un límite de palabra después del valor.
    # La estructura real es REGAGE + año + letra + 11 dígitos.
    regage = _first_match(
        [
            r"(REGAGE\d{2}[A-Za-z]\d{11})",

            r"N[úu]mero\s+de\s+registro\s*[:\-]?"
            r"[ \t\r\n]*"
            r"(REGAGE\d{2}[A-Za-z]\d{11})",

            r"N[º°]\.?\s*REGISTRO\s*[:\-]?"
            r"[ \t\r\n]*"
            r"(REGAGE\d{2}[A-Za-z]\d{11})",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
        ),
    )

    # Conservamos el formato administrativo habitual:
    # REGAGE26e00041927758
    if regage:
        regage = (
            regage[:8].upper()
            + regage[8].lower()
            + regage[9:]
        )

    fecha_registro = _first_match(
        [
            r"Fecha\s+y\s+hora\s+de\s+registro\s+en\s+"
            r"(\d{2}/\d{2}/\d{4}\s+"
            r"\d{2}:\d{2}:\d{2})",

            r"FECHA\s+Y\s+HORA\s+DOCUMENTO\s+"
            r"(\d{2}/\d{2}/\d{4}\s+"
            r"\d{2}:\d{2}:\d{2})",
        ],
        text,
    )
    fecha_registro = _normalize_datetime(
        fecha_registro
    )

    fecha_presentacion = _first_match(
        [
            r"Fecha\s+presentaci[óo]n\s*:\s*"
            r"(\d{2}/\d{2}/\d{4}\s+"
            r"\d{2}:\d{2}:\d{2})",

            r"Fecha\s+de\s+presentaci[óo]n\s*:\s*"
            r"(\d{2}/\d{2}/\d{4}\s+"
            r"\d{2}:\d{2}:\d{2})",
        ],
        text,
    )
    fecha_presentacion = _normalize_datetime(
        fecha_presentacion
    )

    expediente = _first_match(
        [
            r"\bN[º°]\.?\s*Expediente\s*:\s*"
            r"(\d{12,20})\b",

            r"\bexpte\.?\s+num\.?\s*:\s*"
            r"(\d{12,20})\b",

            r"\bexpediente\s+n[úu]mero\s*:\s*"
            r"(\d{12,20})\b",

            r"\bEXPEDIENTE\s*[:\-]\s*"
            r"(\d{12,20})\b",

            r"\b(\d{15})\b",
        ],
        text,
    )
    expediente = _normalize_expediente(
        expediente
    )

    nie = _first_match(
        [
            r"\bInteresado\b.{0,180}?"
            r"([XYZ]\d{7}[A-Z])\b",

            r"\bNIE\s*[:\-]?\s*"
            r"([XYZ]\d{7}[A-Z])\b",

            r"\b([XYZ]\d{7}[A-Z])\b",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )
    nie = _normalize_nie(nie)

    dir3 = _first_match(
        [
            r"\b([A-Z]{1,3}\d{6,9})\b"
            r"\s*/\s*Ministerio",

            r"\bDIR3\s*[:\-]?\s*"
            r"([A-Z]{1,3}\d{6,9})\b",

            r"\b(EA\d{7})\b",
        ],
        text,
    ).upper()

    organo = _first_match(
        [
            r"Unidad\s+de\s+tramitaci[óo]n\s*"
            r"destino/Centro\s+directivo\s*:\s*"
            r"(.+?)\s*-\s*[A-Z]{1,3}\d{6,9}",

            r"Unidad\s+de\s+tramitaci[óo]n\s*"
            r"destino/Centro\s+directivo\s*:\s*"
            r"([^\n\r]+)",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    documento_aportado = _first_match(
        [
            r"\bAdjuntos\b.{0,250}?"
            r"\bNombre\s*:\s*([^\n\r]+)",

            r"\bObservaciones\s*:\s*"
            r"(JUST[^\n\r]{3,100})",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    resumen = _first_match(
        [
            r"Resumen/Asunto\s*:\s*"
            r"(.+?)"
            r"(?:Unidad\s+de\s+tramitaci[óo]n|"
            r"Ref\.\s*Externa|N[º°]\.\s*Expediente)",

            r"Formulario\s+Presentaci[óo]n\s*"
            r"T[íi]tulo\s*:\s*(.+?)"
            r"El\s+registro\s+realizado",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    is_tax_submission = any(
        token in normalized_upper
        for token in (
            "JUST ABONO TASA",
            "ABONO TASA",
            "JUSTIFICANTE DE TASA",
            "JUSTIFICANTE TASA",
            "PAGO DE TASA",
            "APORTACIÓN DE TASA",
            "APORTACION DE TASA",
        )
    )

    warnings = []

    required = {
        "fecha_registro":
            fecha_registro,
        "csv_geiser":
            csv_value,
        "numero_registro_regage":
            regage,
        "numero_expediente_extranjeria":
            expediente,
    }

    for key, value in required.items():
        if value:
            continue

        labels = {
            "fecha_registro":
                "No se detectó la fecha de registro",
            "csv_geiser":
                "No se detectó el CSV GEISER",
            "numero_registro_regage":
                "No se detectó el número REGAGE",
            "numero_expediente_extranjeria":
                "No se detectó el número de expediente",
        }

        warnings.append(labels[key])

    if not nie:
        warnings.append(
            "No se detectó el NIE del interesado"
        )

    if not is_tax_submission:
        warnings.append(
            "No se pudo confirmar que la documentación "
            "aportada corresponda a una tasa"
        )

    detected_count = sum(
        bool(value)
        for value in (
            fecha_registro,
            csv_value,
            regage,
            expediente,
            nie,
            dir3,
            documento_aportado,
        )
    )

    return {
        "format":
            "JUSTIFICANTE_APORTACION_TASA_GEISER",
        "fecha_registro":
            fecha_registro,
        "fecha_presentacion":
            fecha_presentacion,
        "csv_geiser":
            csv_value,
        "numero_registro_regage":
            regage,
        "numero_expediente_extranjeria":
            expediente,
        "nie_detectado":
            nie,
        "unidad_tramitacion_codigo":
            dir3,
        "unidad_tramitacion_nombre":
            organo,
        "documento_aportado":
            documento_aportado,
        "resumen_asunto":
            resumen,
        "aportacion_tasa_confirmada":
            is_tax_submission,
        "estado_tasa":
            "APORTADA",
        "warnings":
            warnings,
        "confidence":
            round(detected_count / 7, 2),
    }


def extract_justificante_aportacion_tasa(path):
    path = Path(path)

    result = extract_tax_submission_text(
        extract_pdf_text(path)
    )

    result["sha256"] = calculate_sha256(path)
    result["source_path"] = str(path)

    return result
