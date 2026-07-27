import hashlib
import re
from datetime import datetime
from pathlib import Path


SUPPORTED_EXTENSIONS = {".pdf"}


def _clean(value):
    return str(value or "").strip()


def _compact(value):
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
        match = re.search(
            pattern,
            text,
            flags,
        )

        if not match:
            continue

        value = (
            match.group(1)
            if match.lastindex
            else match.group(0)
        )

        value = _compact(value)

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
            "La resolución debe ser un PDF"
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


def _extract_denial_reason(text):
    """
    Localiza primero los párrafos argumentativos inmediatamente
    anteriores al acuerdo de denegación.

    Evita copiar todos los fundamentos jurídicos genéricos.
    """
    patterns = [
        (
            r"(En\s+este\s+caso,\s+no\s+procede\s+"
            r"la\s+concesi[óo]n.+?)"
            r"(?=\s*Vistos\s+los\s+art[íi]culos|\s*ACUERDA)"
        ),
        (
            r"(No\s+procede\s+la\s+concesi[óo]n.+?)"
            r"(?=\s*Vistos\s+los\s+art[íi]culos|\s*ACUERDA)"
        ),
        (
            r"(?:MOTIVO|CAUSA)\s+DE\s+DENEGACI[ÓO]N\s*:?\s*"
            r"(.+?)"
            r"(?=\s*RECURSOS|\s*ACUERDA|\Z)"
        ),
        (
            r"(?:ACUERDA|RESUELVE).{0,200}?"
            r"DENEGAR.+?"
            r"(?:por\s+cuanto|debido\s+a|por\s+no\s+)"
            r"(.+?)"
            r"(?=\s*RECURSOS|\Z)"
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

        if match:
            reason = _compact(
                match.group(1)
            )

            if reason:
                return reason

    return ""


def _extract_departure_deadline_days(text):
    match = re.search(
        r"abandonar\s+el\s+pa[ií]s\s+en\s+el\s+plazo\s+de\s+"
        r"(quince|15|\d+)\s+d[ií]as",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    value = match.group(1).lower()

    if value == "quince":
        return 15

    return int(value) if value.isdigit() else None


def _extract_appeal_deadline_months(text):
    match = re.search(
        r"recurso\s+(?:administrativo\s+)?de\s+reposici[óo]n"
        r".{0,250}?"
        r"plazo\s+de\s+(un|uno|1|\d+)\s+mes",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if not match:
        return None

    value = match.group(1).lower()

    if value in {"un", "uno", "1"}:
        return 1

    return int(value) if value.isdigit() else None


def _extract_court_deadline_months(text):
    match = re.search(
        r"recurso\s+(?:jurisdiccional|"
        r"contencioso-administrativo)"
        r".{0,350}?"
        r"plazo\s+de\s+(dos|2|\d+)\s+mes",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if not match:
        return None

    value = match.group(1).lower()

    if value == "dos":
        return 2

    return int(value) if value.isdigit() else None


def extract_denial_resolution_text(text):
    text = str(text or "")
    compact_upper = _compact(text).upper()

    csv_value = _first_match(
        [
            r"\bCSV\s*:\s*"
            r"([A-Z]{2,12}-[0-9A-Za-z-]{15,})",

            r"\b(CNO-(?:[0-9A-Za-z]{4,}-){4,}"
            r"[0-9A-Za-z]{4,})\b",
        ],
        text,
    ).strip(".,;: ")

    expediente = _first_match(
        [
            r"Expediente\s+n[º°]\s*:\s*"
            r"(\d{12,20})",

            r"N[º°]\.?\s*Expediente\s*:\s*"
            r"(\d{12,20})",

            r"Expediente\s*N[º°]\s*"
            r"(\d{12,20})",

            r"@@@(\d{12,20})@@@",

            r"\b(\d{15})\b",
        ],
        text,
    )
    expediente = _normalize_expediente(
        expediente
    )

    nie = _first_match(
        [
            r"N\.?\s*I\.?\s*E\.?\s*:\s*"
            r"([XYZ]\d{7}[A-Z])",

            r"\bNIE\s*:\s*"
            r"([XYZ]\d{7}[A-Z])",

            r"\b([XYZ]\d{7}[A-Z])\b",
        ],
        text,
    )
    nie = _normalize_nie(nie)

    fecha_resolucion = _first_match(
        [
            r"REGISTRO\s+GENERAL\s+DE\s+SALIDA\s+"
            r"(\d{2}/\d{2}/\d{2,4})",

            r"(?:Oviedo|Madrid|Le[óo]n|"
            r"Barcelona|Valencia),\s+a\s+"
            r"(\d{1,2}\s+de\s+[A-Za-záéíóúñ]+\s+de\s+\d{4})",

            r"\bFECHA\s*:?\s*"
            r"(\d{2}/\d{2}/\d{4})",
        ],
        text,
    )

    if re.fullmatch(
        r"\d{2}/\d{2}/\d{2}",
        fecha_resolucion,
    ):
        day, month, year = (
            fecha_resolucion.split("/")
        )
        fecha_resolucion = (
            f"{day}/{month}/20{year}"
        )

    fecha_resolucion = _normalize_date(
        fecha_resolucion
    )

    # Fecha de firma como respaldo cuando no se localiza
    # la fecha administrativa principal.
    if not fecha_resolucion:
        fecha_firma = _first_match(
            r"FIRMANTE\(1\).+?"
            r"FECHA\s*:\s*"
            r"(\d{2}/\d{2}/\d{4})",
            text,
            flags=(
                re.IGNORECASE
                | re.MULTILINE
                | re.DOTALL
            ),
        )
        fecha_resolucion = _normalize_date(
            fecha_firma
        )

    dir3 = _first_match(
        [
            r"\bDIR3\s*:?\s*"
            r"([A-Z]{1,3}\d{6,9})",

            r"\b(EA\d{7})\b",
        ],
        text,
    ).upper()

    organo = _first_match(
        [
            r"\b(DELEGACI[ÓO]N\s+DEL\s+GOBIERNO"
            r"\s+EN\s+[A-ZÁÉÍÓÚÜÑ ]+)",

            r"\b(SUBDELEGACI[ÓO]N\s+DEL\s+GOBIERNO"
            r"\s+EN\s+[A-ZÁÉÍÓÚÜÑ ]+)",

            r"\b(OFICINA\s+DE\s+EXTRANJER[ÍI]A)",
        ],
        text,
    )

    reason = _extract_denial_reason(text)

    denial_confirmed = any(
        token in compact_upper
        for token in (
            "DENEGAR LA AUTORIZACIÓN",
            "DENEGAR LA AUTORIZACION",
            "RESOLUCIÓN DENEGATORIA",
            "RESOLUCION DENEGATORIA",
            "ACUERDA DENEGAR",
            "RESUELVE DENEGAR",
        )
    )

    ends_administrative_route = (
        "PONE FIN A LA VÍA ADMINISTRATIVA"
        in compact_upper
        or "PONE FIN A LA VIA ADMINISTRATIVA"
        in compact_upper
        or "AGOTA LA VÍA ADMINISTRATIVA"
        in compact_upper
        or "AGOTA LA VIA ADMINISTRATIVA"
        in compact_upper
    )

    warnings = []

    for value, message in [
        (
            denial_confirmed,
            "No se pudo confirmar que la resolución sea denegatoria",
        ),
        (
            fecha_resolucion,
            "No se detectó la fecha de resolución",
        ),
        (
            expediente,
            "No se detectó el número de expediente",
        ),
        (
            nie,
            "No se detectó el NIE",
        ),
        (
            reason,
            "No se pudo extraer automáticamente el motivo",
        ),
    ]:
        if not value:
            warnings.append(message)

    detected_count = sum(
        bool(value)
        for value in (
            denial_confirmed,
            fecha_resolucion,
            expediente,
            nie,
            csv_value,
            organo,
            reason,
        )
    )

    return {
        "format":
            "RESOLUCION_DENEGATORIA_EXTRANJERIA",
        "fecha_resolucion":
            fecha_resolucion,
        "csv_resolucion":
            csv_value,
        "numero_expediente_extranjeria":
            expediente,
        "nie_detectado":
            nie,
        "unidad_tramitacion_nombre":
            organo,
        "unidad_tramitacion_codigo":
            dir3,
        "motivo_denegacion_detectado":
            reason,
        "motivo_denegacion_abogado":
            reason,
        "fin_via_administrativa":
            ends_administrative_route,
        "recurso_reposicion_meses":
            _extract_appeal_deadline_months(
                text
            ),
        "recurso_contencioso_meses":
            _extract_court_deadline_months(
                text
            ),
        "plazo_salida_dias":
            _extract_departure_deadline_days(
                text
            ),
        "estado_resolucion":
            "DENEGATORIA",
        "resolucion_denegatoria_confirmada":
            denial_confirmed,
        "warnings":
            warnings,
        "confidence":
            round(detected_count / 7, 2),
    }


def extract_resolucion_denegacion(path):
    path = Path(path)

    result = extract_denial_resolution_text(
        extract_pdf_text(path)
    )

    result["sha256"] = calculate_sha256(path)
    result["source_path"] = str(path)

    return result
