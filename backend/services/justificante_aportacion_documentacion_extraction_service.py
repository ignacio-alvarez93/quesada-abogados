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

    for format_string in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
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
    """
    Extrae los adjuntos mediante lectura por líneas.

    Solo considera documento una línea Nombre: cuyo valor
    tenga una extensión de archivo. Después recoge Hash,
    Validez, Tipo y Observaciones hasta el siguiente archivo.
    """
    lines = str(text or "").splitlines()
    documents = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()

        name_match = re.match(
            r"^Nombre\s*:\s*(.+?)\s*$",
            line,
            flags=re.IGNORECASE,
        )

        if not name_match:
            index += 1
            continue

        name = _clean(name_match.group(1))

        # Excluye nombres de personas y otros campos Nombre:
        # únicamente admite valores con apariencia de archivo.
        if not re.search(
            r"\.[A-Za-z0-9]{2,10}$",
            name,
        ):
            index += 1
            continue

        document = {
            "nombre": name,
            "observaciones": "",
            "hash": "",
            "validez": "",
            "tipo": "",
        }

        index += 1
        observation_lines = []
        collecting_observations = False

        while index < len(lines):
            current = lines[index].strip()

            # Comienza el siguiente documento.
            next_name = re.match(
                r"^Nombre\s*:\s*(.+?)\s*$",
                current,
                flags=re.IGNORECASE,
            )

            if next_name and re.search(
                r"\.[A-Za-z0-9]{2,10}$",
                _clean(next_name.group(1)),
            ):
                break

            # Final del bloque de adjuntos.
            if re.match(
                r"^(?:El\s+registro\s+realizado|"
                r"Formulario\s+Presentaci[óo]n|"
                r"Código\s+seguro\s+de\s+Verificaci[óo]n)",
                current,
                flags=re.IGNORECASE,
            ):
                break

            hash_match = re.match(
                r"^Hash(?:\s*\(SHA-512\))?"
                r"\s*:\s*([0-9A-Fa-f]{16,128})",
                current,
                flags=re.IGNORECASE,
            )

            if hash_match:
                document["hash"] = (
                    hash_match.group(1).upper()
                )
                collecting_observations = False
                index += 1
                continue

            validity_match = re.match(
                r"^Validez\s*:\s*(.*)$",
                current,
                flags=re.IGNORECASE,
            )

            if validity_match:
                document["validez"] = _compact_spaces(
                    validity_match.group(1)
                )
                collecting_observations = False
                index += 1
                continue

            type_match = re.match(
                r"^Tipo\s*:\s*(.*)$",
                current,
                flags=re.IGNORECASE,
            )

            if type_match:
                document["tipo"] = _compact_spaces(
                    type_match.group(1)
                )
                collecting_observations = False
                index += 1
                continue

            observation_match = re.match(
                r"^Observaciones\s*:\s*(.*)$",
                current,
                flags=re.IGNORECASE,
            )

            if observation_match:
                first_line = _clean(
                    observation_match.group(1)
                )

                if first_line:
                    observation_lines.append(first_line)

                collecting_observations = True
                index += 1
                continue

            if collecting_observations and current:
                # No incorporar cabeceras administrativas.
                if not re.match(
                    r"^(?:Tamaño\s*\(Bytes\)|"
                    r"Validez|Tipo|Hash)\s*:",
                    current,
                    flags=re.IGNORECASE,
                ):
                    observation_lines.append(current)

            index += 1

        document["observaciones"] = _compact_spaces(
            " ".join(observation_lines)
        )

        # Un adjunto administrativo debería tener hash.
        # Se conserva aunque falte, pero se evita cualquier
        # Nombre: ajeno mediante la validación de extensión.
        documents.append(document)

    return documents


def _attachments_as_text(documents):
    lines = []

    for index, document in enumerate(
        documents,
        start=1,
    ):
        name = (
            document.get("nombre")
            or "Documento"
        )
        observation = (
            document.get("observaciones")
            or ""
        )

        lines.append(
            f"{index}. {name}"
        )

        if observation:
            lines.append(
                f"   {observation}"
            )

    return "\n".join(lines)


def extract_document_submission_text(text):
    text = str(text or "")

    csv_value = _first_match(
        [
            r"C[óo]digo\s+seguro\s+de\s+"
            r"Verificaci[óo]n\s*:\s*"
            r"(GEISER-[0-9A-Za-z-]{20,})",

            r"\bCSV\s*:\s*"
            r"(GEISER-[0-9A-Za-z-]{20,})",

            r"\b(GEISER-(?:[0-9A-Za-z]{4,}-){4,}"
            r"[0-9A-Za-z]{4,})\b",
        ],
        text,
    ).strip(".,;: ")

    regage = _first_match(
        [
            # Formato real del justificante:
            # REGAGE26e00008209793
            r"(REGAGE\d{2}[A-Za-z]\d{11})",

            r"N[úu]mero\s+de\s+registro\s*:\s*"
            r"(REGAGE\d{2}[A-Za-z]\d{11})",
        ],
        text,
    )

    if regage:
        regage = (
            regage[:8].upper()
            + regage[8].lower()
            + regage[9:]
        )

    fecha_registro = _first_match(
        r"Fecha\s+y\s+hora\s+de\s+registro\s+en\s+"
        r"(\d{2}/\d{2}/\d{4}\s+"
        r"\d{2}:\d{2}:\d{2})",
        text,
    )
    fecha_registro = _normalize_datetime(
        fecha_registro
    )

    fecha_presentacion = _first_match(
        r"Fecha\s+presentaci[óo]n\s*:\s*"
        r"(\d{2}/\d{2}/\d{4}\s+"
        r"\d{2}:\d{2}:\d{2})",
        text,
    )
    fecha_presentacion = _normalize_datetime(
        fecha_presentacion
    )

    expediente = _first_match(
        [
            r"expte\.?\s+num\.?\s*:\s*"
            r"(\d{12,20})",

            r"N[º°]\.?\s*Expediente\s*:\s*"
            r"(\d{12,20})",

            r"expediente\s+n[úu]mero\s*:\s*"
            r"(\d{12,20})",

            r"\b(\d{15})\b",
        ],
        text,
    )
    expediente = _normalize_expediente(
        expediente
    )

    nie = _first_match(
        [
            r"\bInteresado\b.{0,200}?"
            r"([XYZ]\d{7}[A-Z])",

            r"\bNIE\s*:\s*"
            r"([XYZ]\d{7}[A-Z])",

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
            r"\b(EA\d{7})\b"
            r"\s*/\s*Ministerio",

            r"\bDIR3\s*:\s*"
            r"(EA\d{7})",

            r"\b(EA\d{7})\b",
        ],
        text,
    ).upper()

    organo = _first_match(
        [
            r"Unidad\s+de\s+tramitaci[óo]n"
            r"\s+destino/Centro\s+directivo\s*:\s*"
            r"(.+?)\s*-\s*EA\d{7}",

            r"(Delegaci[óo]n\s+del\s+Gobierno"
            r"\s+en\s+[^\n\r-]+)",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    summary = _first_match(
        [
            r"Resumen/Asunto\s*:\s*"
            r"(.+?)"
            r"(?=Unidad\s+de\s+tramitaci[óo]n)",

            r"Formulario\s+Presentaci[óo]n"
            r".*?T[íi]tulo\s*:\s*"
            r"(.+?)"
            r"(?=El\s+registro\s+realizado)",
        ],
        text,
        flags=(
            re.IGNORECASE
            | re.MULTILINE
            | re.DOTALL
        ),
    )

    documents = _extract_attachments(text)
    documents_text = _attachments_as_text(
        documents
    )

    warnings = []

    for value, message in [
        (
            fecha_registro,
            "No se detectó la fecha de registro",
        ),
        (
            csv_value,
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
        (
            documents,
            "No se detectaron los documentos aportados",
        ),
    ]:
        if not value:
            warnings.append(message)

    detected_count = sum(
        bool(value)
        for value in (
            fecha_registro,
            csv_value,
            regage,
            expediente,
            nie,
            dir3,
            documents,
        )
    )

    return {
        "format":
            "JUSTIFICANTE_APORTACION_DOCUMENTACION_GEISER",
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
        "resumen_asunto":
            summary,
        "documentos_aportados":
            documents,
        "documentos_aportados_texto":
            documents_text,
        "notas_aportacion_abogado":
            "",
        "numero_documentos_aportados":
            len(documents),
        "estado_aportacion":
            "APORTADA",
        "warnings":
            warnings,
        "confidence":
            round(detected_count / 7, 2),
    }


def extract_justificante_aportacion_documentacion(
    path,
):
    path = Path(path)

    result = extract_document_submission_text(
        extract_pdf_text(path)
    )

    result["sha256"] = calculate_sha256(path)
    result["source_path"] = str(path)

    return result
