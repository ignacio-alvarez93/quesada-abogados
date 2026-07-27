import hashlib
import re
from datetime import datetime
from pathlib import Path


def _clean(value):
    return str(value or "").strip()


def _compact(value):
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

        value = _compact(value)

        if value:
            return value

    return ""


def _normalize_datetime(value):
    value = _clean(value)

    if not value:
        return ""

    value = re.sub(
        r"\s*\(Horario\s+peninsular\)\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    )

    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(
                value,
                fmt,
            ).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return ""


def _normalize_regage(value):
    value = re.sub(
        r"[^A-Za-z0-9]",
        "",
        _clean(value),
    )

    match = re.fullmatch(
        r"(?i)REGAGE(\d{2})([A-Za-z])(\d{8,})",
        value,
    )

    if not match:
        return ""

    year, separator, number = match.groups()

    # Formato canónico de los asientos GEISER:
    # REGAGE26e00019933335
    return (
        "REGAGE"
        + year
        + separator.lower()
        + number
    )


def _normalize_nie(value):
    value = re.sub(
        r"[^A-Za-z0-9]",
        "",
        _clean(value),
    ).upper()

    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", value):
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

    if path.suffix.lower() != ".pdf":
        raise ValueError(
            "El justificante debe ser un PDF"
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


def _extract_attachments(text):
    names = re.findall(
        r"Nombre\s*:\s*([^\r\n]+?\."
        r"(?:pdf|docx?|jpe?g|png|tiff?))"
        r"(?=\s|$)",
        text,
        flags=re.IGNORECASE,
    )

    result = []
    seen = set()

    for match in names:
        # re.findall devuelve aquí una cadena completa,
        # no una tupla de grupos.
        name = _compact(match).strip(" .")

        key = name.casefold()

        if name and key not in seen:
            seen.add(key)
            result.append(name)

    return result


def extract_extension_receipt_text(text):
    text = str(text or "")
    compact_upper = _compact(text).upper()

    csv_geiser = _first_match(
        [
            r"C[óo]digo\s+seguro\s+de\s+"
            r"Verificaci[óo]n\s*:\s*"
            r"(GEISER-[A-Za-z0-9-]+)",

            r"\b(GEISER-[A-Za-z0-9-]+)\b",
        ],
        text,
    )

    fecha_hora = _first_match(
        [
            r"Fecha\s+y\s+hora\s+de\s+registro\s+en\s+"
            r"(\d{2}/\d{2}/\d{4}\s+"
            r"\d{2}:\d{2}(?::\d{2})?"
            r"(?:\s*\(Horario\s+peninsular\))?)",

            r"Fecha\s+presentaci[óo]n\s*:\s*"
            r"(\d{2}/\d{2}/\d{4}\s+"
            r"\d{2}:\d{2}(?::\d{2})?)",
        ],
        text,
    )
    fecha_hora = _normalize_datetime(fecha_hora)

    regage = _first_match(
        [
            # Formato habitual:
            # Número de registro: REGAGE26e00019933335
            r"N[úu]mero\s+de\s+registro\s*:\s*"
            r"(REGAGE\s*\d{2}\s*[A-Za-z]\s*"
            r"\d{8,})",

            # Respaldo para el bloque inferior.
            r"(REGAGE\s*\d{2}\s*[A-Za-z]\s*"
            r"\d{8,})",

            # Variante compacta genérica.
            r"(REGAGE[A-Za-z0-9]{10,})",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    regage = _normalize_regage(regage)

    # Respaldo definitivo para PDFs cuyo layout introduce
    # espacios, saltos u otros caracteres entre las letras
    # y cifras del número REGAGE.
    if not regage:
        compact_alphanumeric = re.sub(
            r"[^A-Za-z0-9]",
            "",
            text,
        )

        compact_match = re.search(
            r"REGAGE\d{2}[A-Za-z]\d{8,}",
            compact_alphanumeric,
            flags=re.IGNORECASE,
        )

        if compact_match:
            regage = _normalize_regage(
                compact_match.group(0)
            )

    expediente = _first_match(
        [
            r"N[º°]\.?\s*Expediente\s*:\s*"
            r"(\d{12,20})",

            r"expte\.?\s*num\.?\s*:\s*"
            r"(\d{12,20})",

            r"expediente\s+n[úu]mero\s*:\s*"
            r"(\d{12,20})",
        ],
        text,
    )

    nie = _first_match(
        [
            r"\b([XYZ]\d{7}[A-Z])\b",
        ],
        text,
    )
    nie = _normalize_nie(nie)

    dir3 = _first_match(
        [
            r"Oficina\s+de\s+Extranjer[íi]a"
            r".+?-\s*([A-Z]{2}\d{7})",

            r"\b(EA\d{7})\b",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    ).upper()

    organo = _first_match(
        [
            r"Unidad\s+de\s+tramitaci[óo]n"
            r".+?:\s*(Oficina\s+de\s+"
            r"Extranjer[íi]a\s+en\s+[^\r\n-]+)",

            r"(Oficina\s+de\s+Extranjer[íi]a"
            r"\s+en\s+[^\r\n-]+)",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    observations = _first_match(
        [
            r"Observaciones\s*:\s*"
            r"(SOLICITUD\s+AMPLIACI[ÓO]N"
            r".+?)(?=\s*Formulario\s+Presentaci[óo]n)",

            r"(SOLICITUD\s+AMPLIACI[ÓO]N"
            r"\s+PLAZO\s+REQUERIMIENTO)",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    attachments = _extract_attachments(text)

    confirmed = (
        "AMPLIACION PLAZO" in compact_upper
        or "AMPLIACIÓN PLAZO" in compact_upper
        or "AMPLIACION_PLAZO" in compact_upper
    )

    warnings = []

    for value, message in [
        (
            confirmed,
            "No se pudo confirmar que sea una ampliación de plazo",
        ),
        (
            fecha_hora,
            "No se detectó la fecha de registro",
        ),
        (
            csv_geiser,
            "No se detectó el CSV GEISER",
        ),
        (
            regage,
            "No se detectó el REGAGE",
        ),
        (
            expediente,
            "No se detectó el número de expediente",
        ),
    ]:
        if not value:
            warnings.append(message)

    detected_count = sum(
        bool(value)
        for value in (
            confirmed,
            fecha_hora,
            csv_geiser,
            regage,
            expediente,
            nie,
            attachments,
            observations,
        )
    )

    attachment_text = "\n".join(
        f"{index}. {name}"
        for index, name in enumerate(
            attachments,
            start=1,
        )
    )

    return {
        "format":
            "JUSTIFICANTE_AMPLIACION_PLAZO_GEISER",
        "solicitud_ampliacion_confirmada":
            confirmed,
        "fecha_hora_registro":
            fecha_hora,
        "fecha_registro":
            fecha_hora[:10] if fecha_hora else "",
        "csv_geiser":
            csv_geiser,
        "numero_registro_regage":
            regage,
        "numero_expediente_extranjeria":
            expediente,
        "nie_detectado":
            nie,
        "unidad_tramitacion_nombre":
            organo,
        "unidad_tramitacion_codigo":
            dir3,
        "documentos_adjuntos":
            attachments,
        "documentos_adjuntos_texto":
            attachment_text,
        "observaciones_registro":
            observations,
        "motivo_ampliacion_abogado":
            observations,
        "plazo_solicitado_dias":
            None,
        "nueva_fecha_limite_solicitada":
            "",
        "estado_solicitud_ampliacion":
            "PRESENTADA",
        "warnings":
            warnings,
        "confidence":
            round(detected_count / 8, 2),
    }


def extract_justificante_ampliacion_plazo(path):
    path = Path(path)

    result = extract_extension_receipt_text(
        extract_pdf_text(path)
    )

    result["sha256"] = calculate_sha256(path)
    result["source_path"] = str(path)

    return result
