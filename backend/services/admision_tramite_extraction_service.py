import hashlib
import re
from datetime import datetime
from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf"}


def _clean(value):
    return str(value or "").strip()


def _compact_spaces(value):
    return re.sub(r"\s+", " ", _clean(value)).strip()


def _first_match(patterns, text, flags=re.IGNORECASE | re.MULTILINE):
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


def _normalize_date(value):
    value = _clean(value)

    if not value:
        return ""

    for format_string in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(
                value,
                format_string,
            ).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return ""


def _normalize_nie(value):
    value = re.sub(
        r"[^0-9A-Za-z]",
        "",
        _clean(value),
    ).upper()

    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", value):
        return value

    return ""


def _normalize_expediente(value):
    value = re.sub(
        r"\D",
        "",
        _clean(value),
    )

    # Los números de expediente de Extranjería suelen ser cadenas
    # numéricas largas. Se evita aceptar teléfonos o fechas.
    if 12 <= len(value) <= 20:
        return value

    return ""


def _normalize_csv(value):
    value = _clean(value).strip(".,;: ")

    if not value:
        return ""

    return value


def _normalize_amount_centimos(value):
    value = _clean(value)

    if not value:
        return None

    normalized = (
        value
        .replace(".", "")
        .replace(",", ".")
        .replace("€", "")
        .strip()
    )

    try:
        return int(
            round(float(normalized) * 100)
        )
    except (TypeError, ValueError):
        return None


def _extract_tax_data(text):
    normalized = _compact_spaces(text)

    tasa_requerida = bool(
        re.search(
            r"""
            (
                NO\s+CONSTA\s+QUE\s+SE\s+HAYAN\s+PAGADO
                |
                REQUERIMIENTO\s+DE\s+TASA
                |
                SE\s+LE\s+REQUIERE.{0,250}PAGO\s+DE\s+LA[S]?\s+TASA[S]?
                |
                TASA\s+790
            )
            """,
            normalized,
            flags=(
                re.IGNORECASE
                | re.DOTALL
                | re.VERBOSE
            ),
        )
    )

    modelo = _first_match(
        [
            r"\bTasa\s+790\b",
            r"\bModelo\s+790\b",
        ],
        text,
    )

    codigo = _first_match(
        [
            r"\b790\s*[-–]?\s*c[óo]digo\s*"
            r"([0-9]{3})\b",
            r"\bCODIGO\s+([0-9]{3})\b",
            r"\bC[ÓO]DIGO\s*[:\-]?\s*"
            r"([0-9]{3})\b",
        ],
        text,
    )

    amount_value = _first_match(
        [
            r"\bTasa\s+790\s*[-–]?\s*c[óo]digo\s*"
            r"[0-9]{3}.{0,180}?"
            r"([0-9]{1,4}[,.][0-9]{2})\s*€",

            r"\bImporte\s+euros?\s*[:\-]?\s*"
            r"([0-9]{1,4}[,.][0-9]{2})",

            r"\b([0-9]{1,4}[,.][0-9]{2})\s*€",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    apartado = _first_match(
        [
            r"\bapartado\s+"
            r"([0-9]+(?:\.[0-9A-Za-z]+)*)\b",

            r"\b(2\.[0-9]+(?:\.[0-9A-Za-z]+)*)\s+"
            r"(?:Autorizaci[óo]n|Residencia|Pr[óo]rroga)",
        ],
        text,
    )

    concepto = _first_match(
        [
            r"""
            Tasa\s+790\s*[-–]?\s*c[óo]digo\s*
            [0-9]{3}
            (?:\s*[-–]\s*apartado\s+
                [0-9]+(?:\.[0-9A-Za-z]+)*
            )?
            \s*
            (?:[-–:]\s*)?
            ([^\n\r€]{8,240})
            """,

            r"""
            Tipo\s+de\s+Autorizaci[óo]n
            \s*
            ([^\n\r]{8,180})
            """,
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.VERBOSE
        ),
    )

    if concepto:
        concepto = re.sub(
            r"[-–]\s*[0-9]{1,4}[,.][0-9]{2}\s*$",
            "",
            concepto,
        ).strip(" -–:.")

    plazo_pago = _first_match(
        r"per[ií]odo\s+de\s+"
        r"(\d{1,2})\s+d[ií]as\s+h[áa]biles",
        text,
    )

    plazo_aportacion = _first_match(
        [
            r"plazo\s+de\s+"
            r"(\d{1,2})\s+d[ií]as\s+"
            r"desde\s+la\s+fecha\s+de[l]?\s+pago",

            r"en\s+el\s+plazo\s+de\s+"
            r"(\d{1,2})\s+d[ií]as\s+"
            r"desde\s+la\s+fecha\s+de[l]?\s+pago",
        ],
        text,
    )

    return {
        "tasa_requerida": tasa_requerida,
        "tasa_modelo": (
            "790"
            if modelo or codigo
            else ""
        ),
        "tasa_codigo": codigo,
        "tasa_importe_centimos":
            _normalize_amount_centimos(amount_value),
        "tasa_apartado": apartado,
        "tasa_concepto": concepto,
        "plazo_pago_dias_habiles": (
            int(plazo_pago)
            if plazo_pago
            else None
        ),
        "plazo_aportacion_dias": (
            int(plazo_aportacion)
            if plazo_aportacion
            else None
        ),
        "estado_tasa": (
            "PENDIENTE"
            if tasa_requerida
            else ""
        ),
    }


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
            "La admisión a trámite debe ser un PDF"
        )

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "No está disponible pypdf"
        ) from exc

    reader = PdfReader(str(path))
    pages = []

    for page in reader.pages:
        pages.append(page.extract_text() or "")

    text = "\n".join(pages).strip()

    if not text:
        raise ValueError(
            "El PDF no contiene texto extraíble"
        )

    return text


def detect_format(text):
    normalized = _compact_spaces(text).upper()

    if (
        "OFICINA DE EXTRANJERÍA" in normalized
        and "EXPEDIENTE:" in normalized
        and "NIE:" in normalized
    ):
        return "EXTRANJERIA_COMMUNICATION_STANDARD"

    if (
        "COMUNICACIÓN DE INICIO" in normalized
        or "ADMITIDA A TRÁMITE" in normalized
        or "ADMITIDA A TRAMITE" in normalized
    ):
        return "EXTRANJERIA_ADMISSION_GENERIC"

    return "UNKNOWN_ADMISSION_FORMAT"


def extract_admission_text(text):
    text = str(text or "")
    normalized = _compact_spaces(text)

    csv_value = _first_match(
        [
            r"\bCSV\s*[:\-]\s*([A-Z]{2,12}-[0-9A-Za-z-]{15,})",
            r"\bC[ÓO]DIGO\s+SEGURO\s+DE\s+"
            r"VERIFICACI[ÓO]N\s*[:\-]\s*"
            r"([A-Z]{2,12}-[0-9A-Za-z-]{15,})",
            r"\b([A-Z]{2,12}-(?:[0-9A-Za-z]{4,}-){3,}"
            r"[0-9A-Za-z]{4,})\b",
        ],
        text,
    )
    csv_value = _normalize_csv(csv_value)

    nie = _first_match(
        [
            r"\bNIE\s*[:\-]\s*([XYZ]\s*\d{7}\s*[A-Z])\b",
            r"\bN\.?\s*I\.?\s*E\.?\s*[:\-]\s*"
            r"([XYZ]\s*\d{7}\s*[A-Z])\b",
            r"\b([XYZ]\s*\d{7}\s*[A-Z])\b",
        ],
        text,
    )
    nie = _normalize_nie(nie)

    numero_expediente = _first_match(
        [
            # Formato actual:
            # EXPEDIENTE: 330020260007750
            r"\bEXPEDIENTE\s*[:\-]\s*(\d{12,20})\b",

            # Formatos históricos:
            # Expte Nº 330020260004822
            # Expte N.º 330020260004822
            # Expte: 330020260004822
            r"\bEXPTE\.?\s*"
            r"(?:N\s*[º°o]\.?\s*)?"
            r"[:\-]?\s*(\d{12,20})\b",

            # Consulta por SMS:
            # EXPE 330020260007750
            r"\bEXPE\s+(\d{12,20})\b",

            r"\bN[ÚU]MERO\s+DE\s+EXPEDIENTE\s*"
            r"[:\-]\s*(\d{12,20})\b",

            r"\bN[º°]\s*EXPEDIENTE\s*"
            r"[:\-]\s*(\d{12,20})\b",
        ],
        text,
    )
    numero_expediente = _normalize_expediente(
        numero_expediente
    )

    # En algunos PDF pypdf altera el orden:
    # "En fecha ha tenido entrada ... 17/07/2026".
    # Por eso se prueban varias construcciones.
    fecha = _first_match(
        [
            # Fecha propia de la comunicación:
            # Fecha 21/05/2026
            # Se prioriza frente a la fecha de firma del CSV.
            r"^\s*Fecha\s*[:\-]?\s*"
            r"(\d{2}[/-]\d{2}[/-]\d{4})\s*$",

            # Formato actual:
            # En fecha 17/07/2026 ha tenido entrada...
            r"En\s+fecha\s+"
            r"(\d{2}[/-]\d{2}[/-]\d{4})"
            r".{0,180}?ha\s+tenido\s+entrada",

            r"(\d{2}[/-]\d{2}[/-]\d{4})"
            r".{0,100}?ha\s+tenido\s+entrada",

            # Último fallback etiquetado.
            r"FECHA\s*[:\-]\s*"
            r"(\d{2}[/-]\d{2}[/-]\d{4})",

            r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )
    fecha = _normalize_date(fecha)

    dir3 = _first_match(
        [
            # Formato habitual observado:
            # DIR3: EA0040281
            r"\bDIR3\s*[:\-]\s*"
            r"([A-Z]{1,3}\d{6,9})\b",

            # Fallback específico para unidades EA:
            # EA + 7 dígitos.
            r"\b(EA\d{7})\b",
        ],
        text,
    ).upper()

    solicitante = _first_match(
        [
            r"\bSolicitante\s*[:\-]\s*"
            r"([^\n\r]+)",
            r"\ba\s+favor\s+de\s+"
            r"([A-ZÁÉÍÓÚÜÑ ]{5,})",
        ],
        text,
    )

    tax_data = _extract_tax_data(text)

    result = {
        "format": detect_format(text),
        "fecha_admision_tramite": fecha,
        "csv_admision_tramite": csv_value,
        "nie_detectado": nie,
        "numero_expediente_extranjeria":
            numero_expediente,
        "unidad_tramitacion_codigo": dir3,
        "solicitante_detectado": solicitante,
        **tax_data,
    }

    required = {
        "fecha_admision_tramite":
            "No se detectó la fecha de admisión",
        "csv_admision_tramite":
            "No se detectó el CSV",
        "numero_expediente_extranjeria":
            "No se detectó el número de expediente",
    }

    warnings = [
        message
        for key, message in required.items()
        if not result.get(key)
    ]

    if not nie:
        warnings.append(
            "No se detectó un NIE en el documento"
        )

    detected_count = sum(
        bool(result.get(key))
        for key in (
            "fecha_admision_tramite",
            "csv_admision_tramite",
            "nie_detectado",
            "numero_expediente_extranjeria",
        )
    )

    result["warnings"] = warnings
    result["confidence"] = round(
        detected_count / 4,
        2,
    )

    return result


def extract_admision_tramite(path):
    path = Path(path)
    text = extract_pdf_text(path)

    result = extract_admission_text(text)
    result["sha256"] = calculate_sha256(path)
    result["source_path"] = str(path)
    result["source_name"] = path.name

    return result
