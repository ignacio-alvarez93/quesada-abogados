import json
from datetime import datetime
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError as exc:
    raise ImportError(
        "Falta la dependencia 'pypdf'. Instala con: pip install pypdf "
        "y añade 'pypdf>=6.0.0' a requirements.txt"
    ) from exc

from backend.services import document_template_service


BASE_DIR = Path(__file__).resolve().parents[2]


PDF_FIELD_TYPES = {
    "/Tx": "text",
    "/Btn": "button",
    "/Ch": "choice",
    "/Sig": "signature",
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_code(value):
    return str(value or "").strip().upper().replace(" ", "_")


def _resolve_project_path(value):
    raw = str(value or "").strip().replace("\\", "/").strip()
    if not raw:
        raise ValueError("La ruta del PDF está vacía")

    path = Path(raw)
    if path.is_absolute():
        return path

    return BASE_DIR / path


def _relative_path(path):
    try:
        return str(Path(path).resolve().relative_to(BASE_DIR)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _to_python(value):
    if value is None:
        return None

    try:
        value = value.get_object()
    except Exception:
        pass

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("latin-1", errors="replace")

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (list, tuple)):
        return [_to_python(item) for item in value]

    try:
        return str(value)
    except Exception:
        return None


def _field_type_label(field_type):
    raw = str(field_type or "")
    return PDF_FIELD_TYPES.get(raw, raw.strip("/") or "unknown")


def _flags_info(flags):
    try:
        value = int(flags or 0)
    except Exception:
        value = 0

    return {
        "raw": value,
        "read_only": bool(value & 1),
        "required": bool(value & 2),
        "no_export": bool(value & 4),
    }


def _button_states(field):
    states = []

    explicit_states = field.get("/_States_") if isinstance(field, dict) else None
    if explicit_states:
        for state in explicit_states:
            state_value = str(_to_python(state) or "")
            if state_value and state_value not in states:
                states.append(state_value)

    ap = field.get("/AP") if isinstance(field, dict) else None
    try:
        ap = ap.get_object()
    except Exception:
        pass

    normal_appearance = ap.get("/N") if isinstance(ap, dict) else None
    try:
        normal_appearance = normal_appearance.get_object()
    except Exception:
        pass

    if isinstance(normal_appearance, dict):
        for key in normal_appearance.keys():
            state_value = str(key)
            if state_value and state_value not in states:
                states.append(state_value)

    if "/Off" not in states:
        states.insert(0, "/Off")

    return states


def _annotation_index(reader):
    """
    Mapea nombres de campo a posición de página y rectángulo.

    En muchos PDFs oficiales, get_fields() devuelve los campos pero no siempre
    la página. Esta función recorre anotaciones de páginas para enriquecerlos.
    """
    by_name = {}

    for page_index, page in enumerate(reader.pages):
        annotations = page.get("/Annots") or []
        for annotation_ref in annotations:
            try:
                annotation = annotation_ref.get_object()
            except Exception:
                continue

            if not isinstance(annotation, dict):
                continue

            field_name = annotation.get("/T")
            parent = annotation.get("/Parent")
            parent_obj = None

            try:
                parent_obj = parent.get_object() if parent else None
            except Exception:
                parent_obj = None

            if not field_name and isinstance(parent_obj, dict):
                field_name = parent_obj.get("/T")

            name = str(_to_python(field_name) or "").strip()
            if not name:
                continue

            rect = annotation.get("/Rect")
            info = {
                "page": page_index + 1,
                "rect": _to_python(rect) if rect else None,
            }
            by_name.setdefault(name, info)

    return by_name


def _field_record(name, raw_field, page_info=None, order=0):
    if raw_field is None:
        raw_field = {}

    try:
        field = raw_field.get_object()
    except Exception:
        field = raw_field

    field_type = field.get("/FT") if isinstance(field, dict) else None
    field_flags = _flags_info(field.get("/Ff") if isinstance(field, dict) else 0)

    record = {
        "order": order,
        "name": str(name),
        "type": str(field_type or ""),
        "type_label": _field_type_label(field_type),
        "value": _to_python(field.get("/V") if isinstance(field, dict) else None),
        "default_value": _to_python(field.get("/DV") if isinstance(field, dict) else None),
        "alternate_name": _to_python(field.get("/TU") if isinstance(field, dict) else None),
        "mapping_hint": "",
        "required": field_flags["required"],
        "read_only": field_flags["read_only"],
        "no_export": field_flags["no_export"],
        "flags": field_flags["raw"],
        "page": (page_info or {}).get("page"),
        "rect": (page_info or {}).get("rect"),
    }

    if record["type"] == "/Btn":
        record["states"] = _button_states(field)

    if record["type"] == "/Ch":
        options = field.get("/Opt") if isinstance(field, dict) else None
        record["options"] = _to_python(options) or []

    return record


def inspect_pdf_fields(pdf_path):
    """
    Inspecciona campos AcroForm de un PDF rellenable.

    No rellena PDF.
    No modifica plantillas.
    No toca base de datos.
    """
    resolved_pdf_path = _resolve_project_path(pdf_path)
    if not resolved_pdf_path.exists():
        raise FileNotFoundError(f"No existe el PDF: {_relative_path(resolved_pdf_path)}")

    reader = PdfReader(str(resolved_pdf_path))
    raw_fields = reader.get_fields() or {}
    pages_by_name = _annotation_index(reader)

    fields = []
    for index, (name, raw_field) in enumerate(raw_fields.items(), start=1):
        fields.append(
            _field_record(
                name=name,
                raw_field=raw_field,
                page_info=pages_by_name.get(str(name)),
                order=index,
            )
        )

    return {
        "generated_at": _now(),
        "pdf_path": _relative_path(resolved_pdf_path),
        "page_count": len(reader.pages),
        "field_count": len(fields),
        "fields": fields,
    }


def export_pdf_fields_json(pdf_path, output_json_path=None):
    """
    Exporta fields.json de un PDF rellenable.

    Si no se indica output_json_path, crea fields.json junto al PDF.
    """
    inspection = inspect_pdf_fields(pdf_path)
    resolved_pdf_path = _resolve_project_path(pdf_path)

    if output_json_path:
        output_path = _resolve_project_path(output_json_path)
    else:
        output_path = resolved_pdf_path.parent / "fields.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(inspection, ensure_ascii=False, indent=2), encoding="utf-8")

    inspection["fields_json_path"] = _relative_path(output_path)
    return inspection


def inspect_document_template_pdf_fields(document_template_id):
    """
    Inspecciona los campos PDF asociados a una plantilla documental.
    """
    template = document_template_service.get_document_template(document_template_id)
    if not template:
        raise ValueError(f"No existe plantilla documental id={document_template_id}")

    if str(template.get("template_type") or "").strip().lower() != "pdf":
        raise ValueError("La plantilla documental no es de tipo pdf")

    return inspect_pdf_fields(template.get("template_path"))


def export_document_template_pdf_fields(document_template_id, update_template=True):
    """
    Exporta fields.json de una plantilla documental PDF.

    Si update_template=True, actualiza fields_json_path de la plantilla
    conservando el resto de datos.
    """
    template = document_template_service.get_document_template(document_template_id)
    if not template:
        raise ValueError(f"No existe plantilla documental id={document_template_id}")

    if str(template.get("template_type") or "").strip().lower() != "pdf":
        raise ValueError("La plantilla documental no es de tipo pdf")

    pdf_path = template.get("template_path")
    fields_json_path = template.get("fields_json_path") or ""

    inspection = export_pdf_fields_json(
        pdf_path,
        output_json_path=fields_json_path or None,
    )

    if update_template and not fields_json_path:
        updated = dict(template)
        updated["fields_json_path"] = inspection["fields_json_path"]
        document_template_service.update_document_template(template["id"], updated)

    return inspection


def export_document_template_pdf_fields_by_code(codigo, update_template=True):
    template = document_template_service.get_document_template_by_code(
        _normalize_code(codigo),
        active_only=True,
    )
    if not template:
        raise ValueError(f"No existe plantilla documental activa con código={codigo}")

    return export_document_template_pdf_fields(
        template["id"],
        update_template=update_template,
    )
