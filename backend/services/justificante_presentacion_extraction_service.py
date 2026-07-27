import hashlib
import re
from datetime import datetime
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


FORMAT_GEISER_REGAGE = "GEISER_REGAGE"


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _iso_datetime(value):
    value = _clean(value)
    if not value:
        return ""

    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return ""


def _first_match(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
    match = re.search(pattern, text or "", flags)
    return _clean(match.group(1)) if match else ""


def calculate_sha256(file_path):
    path = Path(file_path)
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def extract_pdf_text(file_path):
    if PdfReader is None:
        raise RuntimeError(
            "Falta la dependencia pypdf. Ejecuta pip install -r requirements.txt"
        )

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el PDF: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError("El justificante de presentación debe ser un PDF")

    reader = PdfReader(str(path))
    pages = []

    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")

    text = "\n".join(pages).strip()

    if not text:
        raise ValueError(
            "El PDF no contiene texto extraíble. Será necesario OCR."
        )

    return text


def detect_document_format(text):
    normalized = _clean(text).upper()

    if (
        "RECIBO DE PRESENTACIÓN EN OFICINA DE REGISTRO" in normalized
        and "GEISER-" in normalized
        and "REGAGE" in normalized
    ):
        return FORMAT_GEISER_REGAGE

    return "UNKNOWN"


def extract_geiser_receipt_from_text(text):
    document_format = detect_document_format(text)
    if document_format != FORMAT_GEISER_REGAGE:
        raise ValueError("El documento no parece un recibo GEISER/REGAGE")

    oficina_full = _first_match(
        r"Oficina:\s*(.+?)(?:\r?\n|Fecha y hora de registro)",
        text,
    )

    oficina_codigo = _first_match(
        r"Oficina:\s*.+?\s+-\s+(O\d{8})",
        text,
    )

    oficina_nombre = oficina_full
    if oficina_codigo:
        oficina_nombre = re.sub(
            rf"\s*-\s*{re.escape(oficina_codigo)}\s*$",
            "",
            oficina_full,
            flags=re.IGNORECASE,
        ).strip()

    unidad_block = _first_match(
        r"Unidad de tramitación\s*destino/Centro directivo:\s*(.+?)(?:\r?\nRef\. Externa:)",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )

    unidad_codigo = _first_match(
        r"Unidad de tramitación\s*destino/Centro directivo:\s*.+?-\s*(EA\d+)",
        text,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )

    unidad_nombre = ""
    organismo = ""

    if unidad_block:
        compact = _clean(unidad_block)
        parts = [part.strip() for part in compact.split("/", 1)]

        first_part = parts[0] if parts else ""
        organismo = parts[1] if len(parts) > 1 else ""

        if unidad_codigo:
            unidad_nombre = re.sub(
                rf"\s*-\s*{re.escape(unidad_codigo)}\s*$",
                "",
                first_part,
                flags=re.IGNORECASE,
            ).strip()
        else:
            unidad_nombre = first_part

    fecha_presentacion_raw = _first_match(
        r"Fecha presentación:\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})",
        text,
    )

    fecha_registro_raw = _first_match(
        r"Fecha y hora de registro(?:\s+en)?\s*"
        r"(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})",
        text,
    )

    # pypdf puede devolver el valor antes del rótulo:
    # REGAGE26e00067195547Número de registro:
    #
    # Por ello se identifica mediante su estructura estable:
    # REGAGE + 2 dígitos de año + letra + 11 dígitos.
    numero_registro = _first_match(
        r"(REGAGE\d{2}[A-Za-z]\d{11})",
        text,
    )

    numero_presentacion = _first_match(
        r"N[º°]\.?\s*Expediente:\s*([A-Z]\d+)",
        text,
    )

    csv_geiser = _first_match(
        r"(GEISER-[0-9A-Za-z-]{20,})",
        text,
    )

    ambito_prefijo = "GEISER" if csv_geiser.upper().startswith("GEISER-") else ""

    result = {
        "format": document_format,
        "numero_presentacion_registro": numero_presentacion,
        "fecha_presentacion_raw": fecha_presentacion_raw,
        "fecha_hora_presentacion": _iso_datetime(fecha_presentacion_raw),
        "fecha_registro_raw": fecha_registro_raw,
        "fecha_hora_registro": _iso_datetime(fecha_registro_raw),
        "numero_registro_regage": numero_registro,
        "oficina_registro_nombre": oficina_nombre,
        "oficina_registro_codigo": oficina_codigo,
        "unidad_tramitacion_nombre": unidad_nombre,
        "unidad_tramitacion_codigo": unidad_codigo,
        "organismo_tramitacion": organismo,
        "registro_ambito_prefijo": ambito_prefijo,
        "registro_csv_geiser": csv_geiser,
        "warnings": [],
    }

    required = {
        "numero_presentacion_registro": "No se detectó el número I33...",
        "fecha_hora_presentacion": "No se detectó la fecha de presentación",
        "numero_registro_regage": "No se detectó el número REGAGE",
        "registro_csv_geiser": "No se detectó el CSV GEISER",
    }

    for key, warning in required.items():
        if not result.get(key):
            result["warnings"].append(warning)

    detected = sum(
        1
        for key in required
        if result.get(key)
    )

    result["confidence"] = round(detected / len(required), 2)

    return result


def extract_justificante_presentacion(file_path):
    path = Path(file_path)
    text = extract_pdf_text(path)
    data = extract_geiser_receipt_from_text(text)

    data["archivo_nombre"] = path.name
    data["archivo_ruta"] = str(path)
    data["sha256"] = calculate_sha256(path)
    data["text_length"] = len(text)

    return data
