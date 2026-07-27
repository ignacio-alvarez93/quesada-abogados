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
        match = re.search(pattern, text, flags)

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


def extract_favorable_resolution_text(text):
    text = str(text or "")
    upper = _compact(text).upper()

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
            r"\bN[º°]\s*EXPEDIENTE\s*"
            r"(\d{12,20})\b",

            r"\bN[º°]\.?\s*EXPEDIENTE\s*:\s*"
            r"(\d{12,20})\b",

            r"\bExpediente\s*N[º°]\s*:\s*"
            r"(\d{12,20})\b",

            r"\bN/REF\s*:?\s*"
            r"(\d{12,20})\b",

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
            r"\bN\.?I\.?E\.?\s*:\s*"
            r"([XYZ]\d{7}[A-Z])",

            r"\bNIE\s*:?\s*"
            r"([XYZ]\d{7}[A-Z])",

            r"\bcon\s+NIE\s+"
            r"([XYZ]\d{7}[A-Z])",

            r"\b([XYZ]\d{7}[A-Z])\b",
        ],
        text,
    )
    nie = _normalize_nie(nie)

    titular = _first_match(
        [
            r"Nombre\s+y\s+apellidos\s+"
            r"([^\n\r]+)",

            r"\bTITULAR\s*:\s*"
            r"([^\n\r]+)",

            r"\bCONCEDER\s+(?:a|la.+?a)\s+"
            r"([A-ZÁÉÍÓÚÜÑ ,'-]{5,100}?)"
            r"\s+(?:con\s+NIE|de\s+nacionalidad)",

            r"\bNombre\s+"
            r"([A-ZÁÉÍÓÚÜÑ ,'-]{3,100})"
            r"\s+Fecha\s+Resoluci[óo]n",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    nacionalidad = _first_match(
        [
            r"\bNacionalidad\s+"
            r"([A-ZÁÉÍÓÚÜÑ]+)",

            r"\bde\s+nacionalidad\s+"
            r"([A-ZÁÉÍÓÚÜÑ]+)",
        ],
        text,
    ).upper()

    pasaporte = _first_match(
        [
            r"\bPasaporte\s+"
            r"([A-Z0-9]{5,20})",

            r"\bPasaporte\s*:\s*"
            r"([A-Z0-9]{5,20})",
        ],
        text,
    ).upper()

    fecha_resolucion = _first_match(
        [
            r"\bFecha\s+Resoluci[óo]n\s+"
            r"(\d{2}/\d{2}/\d{4})",

            r"\bFECHA\s*:?\s*"
            r"(?:[A-Za-zÁÉÍÓÚÜÑ]+,\s*a\s*)?"
            r"(\d{2}/\d{2}/\d{4})",

            r"\bREGISTRO\s+GENERAL\s+(?:DE\s+)?SALIDA\s+"
            r"(\d{2}/\d{2}/\d{2,4})",
        ],
        text,
    )

    if fecha_resolucion:
        parts = fecha_resolucion.split("/")

        if len(parts[-1]) == 2:
            fecha_resolucion = (
                f"{parts[0]}/{parts[1]}/20{parts[2]}"
            )

    fecha_resolucion = _normalize_date(
        fecha_resolucion
    )

    fecha_efectos = _first_match(
        [
            r"\bFecha\s+Efectos\s+"
            r"(\d{2}/\d{2}/\d{4})",

            r"\bcon\s+validez\s+desde\s+"
            r"(?:el(?:\s+d[ií]a)?\s+)?"
            r"(\d{2}/\d{2}/\d{4})",
        ],
        text,
    )
    fecha_efectos = _normalize_date(
        fecha_efectos
    )

    fecha_caducidad = _first_match(
        [
            r"\bFecha\s+Caducidad\s+"
            r"(\d{2}/\d{2}/\d{4})",

            r"\bhasta\s+el\s+"
            r"(\d{2}/\d{2}/\d{4})",
        ],
        text,
    )
    fecha_caducidad = _normalize_date(
        fecha_caducidad
    )

    tipo_autorizacion = _first_match(
        [
            r"\bTipo\s+de\s+autorizaci[óo]n\s+"
            r"(.+?)"
            r"(?=\n|Empresa|Vista\s+la\s+solicitud)",

            r"\bRESUELVE\s+CONCEDER\s+la\s+"
            r"(.+?)"
            r"solicitada\s+por",

            r"\bACUERDO\s+CONCEDER\s+la\s+autorizaci[óo]n\s+de\s+"
            r"(.+?)"
            r"\s+y\s+una\s+autorizaci[óo]n",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
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
            r"\b(SUBDELEGACI[ÓO]N\s+DEL\s+GOBIERNO"
            r"\s+EN\s+[A-ZÁÉÍÓÚÜÑ ]+)",

            r"\b(DELEGACI[ÓO]N\s+DEL\s+GOBIERNO"
            r"\s+EN\s+[A-ZÁÉÍÓÚÜÑ ]+)",

            r"\b(D\.G\.\s+DE\s+GESTI[ÓO]N\s+MIGRATORIA)",

            r"\b(UNIDAD\s+DE\s+TRAMITACI[ÓO]N\s+DE\s+"
            r"EXPEDIENTES\s+DE\s+EXTRANJER[ÍI]A)",
        ],
        text,
    )

    cuenta_ajena = any(
        token in upper
        for token in (
            "TRABAJAR POR CUENTA AJENA",
            "TRABAJO POR CUENTA AJENA",
            "POR CUENTA AJENA",
        )
    )

    cuenta_propia = any(
        token in upper
        for token in (
            "TRABAJAR POR CUENTA PROPIA",
            "TRABAJO POR CUENTA PROPIA",
            "POR CUENTA PROPIA",
        )
    )

    # Algunos modelos dicen únicamente "autorización para trabajar".
    trabajo_generico = (
        "AUTORIZACIÓN PARA TRABAJAR" in upper
        or "AUTORIZACION PARA TRABAJAR" in upper
    )

    eficacia_condicionada_alta = (
        "CONDICIONADA A LA POSTERIOR AFILIACIÓN"
        in upper
        or "CONDICIONADA A LA POSTERIOR AFILIACION"
        in upper
        or "CONDICIONADA AL ALTA"
        in upper
    )

    plazo_alta_meses = None

    if eficacia_condicionada_alta:
        match = re.search(
            r"plazo\s+de\s+"
            r"(UN|UNO|1|\d+)\s+mes",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            value = match.group(1).upper()
            plazo_alta_meses = (
                1
                if value in {"UN", "UNO", "1"}
                else int(value)
                if value.isdigit()
                else None
            )

    requiere_tie = any(
        token in upper
        for token in (
            "TARJETA DE IDENTIDAD DE EXTRANJERO",
            "EXPEDICIÓN DE LA TIE",
            "EXPEDICION DE LA TIE",
            "SOLICITAR PERSONALMENTE LA TARJETA",
        )
    )

    plazo_tie_meses = None

    if requiere_tie:
        tie_match = re.search(
            r"(?:TIE|Tarjeta\s+de\s+Identidad\s+de\s+Extranjero)"
            r".{0,500}?"
            r"plazo\s+de\s+"
            r"(UN|UNO|1|\d+)\s+mes",
            text,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if tie_match:
            value = tie_match.group(1).upper()
            plazo_tie_meses = (
                1
                if value in {"UN", "UNO", "1"}
                else int(value)
                if value.isdigit()
                else None
            )
        else:
            plazo_tie_meses = 1

    favorable = any(
        token in upper
        for token in (
            "RESOLUCIÓN DE CONCESIÓN",
            "RESOLUCION DE CONCESION",
            "RESUELVE CONCEDER",
            "ACUERDO CONCEDER",
        )
    )

    warnings = []

    for value, message in [
        (
            favorable,
            "No se pudo confirmar que la resolución sea favorable",
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
    ]:
        if not value:
            warnings.append(message)

    detected_count = sum(
        bool(value)
        for value in (
            fecha_resolucion,
            expediente,
            nie,
            titular,
            tipo_autorizacion,
            fecha_efectos,
            fecha_caducidad,
            dir3,
        )
    )

    return {
        "format":
            "RESOLUCION_FAVORABLE_EXTRANJERIA",
        "fecha_resolucion":
            fecha_resolucion,
        "fecha_efectos":
            fecha_efectos,
        "fecha_caducidad":
            fecha_caducidad,
        "csv_resolucion":
            csv_value,
        "numero_expediente_extranjeria":
            expediente,
        "nie_detectado":
            nie,
        "titular_detectado":
            titular,
        "nacionalidad":
            nacionalidad,
        "pasaporte":
            pasaporte,
        "tipo_autorizacion":
            tipo_autorizacion,
        "unidad_tramitacion_nombre":
            organo,
        "unidad_tramitacion_codigo":
            dir3,
        "trabajo_cuenta_ajena":
            bool(cuenta_ajena or trabajo_generico),
        "trabajo_cuenta_propia":
            bool(cuenta_propia),
        "eficacia_condicionada_alta_ss":
            eficacia_condicionada_alta,
        "plazo_alta_ss_meses":
            plazo_alta_meses,
        "requiere_tie":
            requiere_tie,
        "plazo_tie_meses":
            plazo_tie_meses,
        "proximos_pasos_abogado":
            "",
        "estado_resolucion":
            "FAVORABLE",
        "resolucion_favorable_confirmada":
            favorable,
        "warnings":
            warnings,
        "confidence":
            round(detected_count / 8, 2),
    }


def extract_resolucion_favorable(path):
    path = Path(path)

    result = extract_favorable_resolution_text(
        extract_pdf_text(path)
    )

    result["sha256"] = calculate_sha256(path)
    result["source_path"] = str(path)

    return result
