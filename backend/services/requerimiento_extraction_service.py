import hashlib
import re
from datetime import datetime
from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf"}


def _clean(value):
    return str(value or "").strip()


def _compact_spaces(value):
    return re.sub(r"\s+", " ", _clean(value)).strip()


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


def _normalize_date(value):
    value = _clean(value)

    for format_string in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d de %B de %Y",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(
                value,
                format_string,
            )
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Fechas españolas escritas.
    months = {
        "enero": "01",
        "febrero": "02",
        "marzo": "03",
        "abril": "04",
        "mayo": "05",
        "junio": "06",
        "julio": "07",
        "agosto": "08",
        "septiembre": "09",
        "octubre": "10",
        "noviembre": "11",
        "diciembre": "12",
    }

    match = re.search(
        r"(\d{1,2})\s+de\s+"
        r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+de\s+"
        r"(\d{4})",
        value,
        flags=re.IGNORECASE,
    )

    if match:
        day, month_name, year = match.groups()
        month = months.get(month_name.lower())

        if month:
            return f"{year}-{month}-{int(day):02d}"

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
    value = re.sub(r"\D", "", _clean(value))

    if 12 <= len(value) <= 20:
        return value

    return ""


def _normalize_csv(value):
    return _clean(value).strip(".,;: ")


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
            "El requerimiento debe ser un PDF"
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


def _extract_required_documentation(text):
    patterns = [
        (
            r"DOCUMENTACI[ÓO]N\s+REQUERIDA"
            r"(?:\s*\([^)]*\))?\s*:\s*"
            r"(.+?)"
            r"(?=\n\s*(?:EL\s+FUNCIONARIO|"
            r"EL\s+JEFE|FIRMADO\s+DIGITALMENTE|"
            r"NOTA\s*:|Podr[áa]\s+presentar|"
            r"@@@)|\Z)"
        ),
        (
            r"DOCUMENTACI[ÓO]N\s+REQUERIDA"
            r"(?:\s*\([^)]*\))?\s*"
            r"(.+?)"
            r"(?=\n\s*(?:EL\s+FUNCIONARIO|"
            r"EL\s+JEFE|FIRMADO\s+DIGITALMENTE|"
            r"NOTA\s*:|Podr[áa]\s+presentar|"
            r"@@@)|\Z)"
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=(
                re.IGNORECASE
                | re.MULTILINE
                | re.DOTALL
            ),
        )

        if not match:
            continue

        value = match.group(1).strip()

        # Eliminar la frase introductoria habitual.
        value = re.sub(
            r"^recuerde\s+que.+?"
            r"(?:referenciado|referenciada)\.?\s*",
            "",
            value,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        ).strip()

        return value

    return ""


def extract_requirement_text(text):
    text = str(text or "")

    csv_value = _first_match(
        [
            r"\bCSV\s*:\s*"
            r"([A-Z]{2,12}-[0-9A-Za-z-]{15,})",

            r"\b(CNO-(?:[0-9A-Za-z]{4,}-){4,}"
            r"[0-9A-Za-z]{4,})\b",
        ],
        text,
    )
    csv_value = _normalize_csv(csv_value)

    expediente = _first_match(
        [
            r"\bExpte\s*N[º°]\s*"
            r"(\d{12,20})\b",

            r"\bN[º°]\.?\s*EXPEDIENTE\s*:\s*"
            r"(\d{12,20})\b",

            r"\bN/REF\s*:\s*"
            r"(\d{12,20})\b",

            r"@@@(\d{12,20})@@@",

            r"\b(\d{15})\b",
        ],
        text,
    )
    expediente = _normalize_expediente(expediente)

    nie = _first_match(
        [
            r"\bN\.?I\.?E\.?\s*:\s*"
            r"([XYZ]\d{7}[A-Z])",

            r"\bNIE\s*:\s*"
            r"([XYZ]\d{7}[A-Z])",

            r"\b([XYZ]\d{7}[A-Z])\b",
        ],
        text,
    )
    nie = _normalize_nie(nie)

    solicitante = _first_match(
        [
            r"\bSolicitante\s*:\s*"
            r"([^\n\r]+)",

            r"\bTITULAR\s*:\s*"
            r"([^\n\r]+)",

            r"\bEn\s+representaci[óo]n\s+de\s*:\s*"
            r"([^\n\r]+)",
        ],
        text,
    )

    fecha = _first_match(
        [
            r"(?m)^\s*Fecha\s+"
            r"(\d{2}/\d{2}/\d{4})\s*$",

            r"\bFECHA\s*:\s*"
            r"(\d{2}/\d{2}/\d{4})",

            r"\bFECHA\s*:\s*"
            r"(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+"
            r"\s+de\s+\d{4})",
        ],
        text,
    )
    fecha = _normalize_date(fecha)

    dir3 = _first_match(
        [
            r"\bDIR3\s*:\s*"
            r"([A-Z]{1,3}\d{6,9})",

            r"\b(EA\d{7})\b",
        ],
        text,
    ).upper()

    organo = _first_match(
        [
            r"\b(DELEGACI[ÓO]N\s+DEL\s+GOBIERNO"
            r"\s+EN\s+[A-ZÁÉÍÓÚÜÑ ]+)",

            r"\b(OFICINA\s+DE\s+EXTRANJER[ÍI]A"
            r"(?:\s+DE\s+[A-ZÁÉÍÓÚÜÑ ]+)?)",
        ],
        text,
    )

    plazo_text = _first_match(
        [
            r"plazo\s+de\s+"
            r"(DIEZ|\d{1,3})\s+D[ÍI]AS",

            r"en\s+el\s+plazo\s+de\s+"
            r"(diez|\d{1,3})\s+d[íi]as",
        ],
        text,
    )

    plazo_map = {
        "DIEZ": 10,
        "diez": 10,
    }

    plazo_dias = (
        plazo_map.get(plazo_text)
        or (
            int(plazo_text)
            if str(plazo_text).isdigit()
            else None
        )
    )

    documentacion = _extract_required_documentation(
        text
    )

    warnings = []

    for key, value, message in [
        (
            "fecha",
            fecha,
            "No se detectó la fecha del requerimiento",
        ),
        (
            "csv",
            csv_value,
            "No se detectó el CSV",
        ),
        (
            "expediente",
            expediente,
            "No se detectó el número de expediente",
        ),
        (
            "nie",
            nie,
            "No se detectó el NIE",
        ),
        (
            "documentacion",
            documentacion,
            "No se pudo extraer la documentación requerida",
        ),
    ]:
        if not value:
            warnings.append(message)

    detected_count = sum(
        bool(value)
        for value in (
            fecha,
            csv_value,
            expediente,
            nie,
            solicitante,
            dir3,
            documentacion,
        )
    )

    return {
        "format": "REQUERIMIENTO_EXTRANJERIA",
        "fecha_requerimiento": fecha,
        "csv_requerimiento": csv_value,
        "numero_expediente_extranjeria":
            expediente,
        "nie_detectado": nie,
        "solicitante_detectado": solicitante,
        "unidad_tramitacion_codigo": dir3,
        "unidad_tramitacion_nombre": organo,
        "plazo_dias": plazo_dias,
        "documentacion_requerida_original":
            documentacion,
        # El abogado podrá modificar este campo en el diálogo.
        "documentacion_requerida_abogado":
            documentacion,
        "estado_requerimiento": "PENDIENTE",
        "warnings": warnings,
        "confidence": round(
            detected_count / 7,
            2,
        ),
    }


def extract_requerimiento(path):
    path = Path(path)

    result = extract_requirement_text(
        extract_pdf_text(path)
    )

    result["sha256"] = calculate_sha256(path)
    result["source_path"] = str(path)

    return result
