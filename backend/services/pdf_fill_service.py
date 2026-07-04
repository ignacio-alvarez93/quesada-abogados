import json
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject

from backend.services import document_generation_service
from backend.services import document_inbox_service
from backend.services import document_template_service


BASE_DIR = Path(__file__).resolve().parents[2]


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _safe_filename(value):
    raw = str(value or "").strip().upper().replace(" ", "_")
    safe = []
    for char in raw:
        if char.isalnum() or char in ("_", "-"):
            safe.append(char)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "PDF"


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


def _load_fields_json(template):
    fields_json_path = str((template or {}).get("fields_json_path") or "").strip()
    if not fields_json_path:
        return {}

    path = _resolve_project_path(fields_json_path)
    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def _template_public(template):
    return {
        "id": template.get("id"),
        "codigo": template.get("codigo"),
        "nombre": template.get("nombre"),
        "categoria": template.get("categoria"),
        "tipo_destino": template.get("tipo_destino"),
        "template_type": template.get("template_type"),
        "template_path": template.get("template_path"),
        "fields_json_path": template.get("fields_json_path"),
        "mapper_destino": template.get("mapper_destino"),
        "requiere_expediente": template.get("requiere_expediente"),
        "activo": template.get("activo"),
    }


def _stringify_pdf_value(value):
    if value is None:
        return ""

    if isinstance(value, bool):
        return "/Yes" if value else "/Off"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]

    return str(value)


def _normalize_checkbox_value(value, allowed_states=None):
    allowed_states = allowed_states or []
    allowed_lookup = {str(state).lower(): str(state) for state in allowed_states}

    if isinstance(value, bool):
        return "/Yes" if value else "/Off"

    raw = str(value or "").strip()
    raw_lower = raw.lower()

    if raw_lower in allowed_lookup:
        return allowed_lookup[raw_lower]

    if raw and not raw.startswith("/"):
        slash_value = f"/{raw}"
        if slash_value.lower() in allowed_lookup:
            return allowed_lookup[slash_value.lower()]

    if raw_lower in ("1", "true", "yes", "y", "si", "sí", "x", "checked", "on"):
        if "/Yes" in allowed_states:
            return "/Yes"
        non_off = [state for state in allowed_states if str(state) != "/Off"]
        return non_off[0] if non_off else "/Yes"

    if raw_lower in ("", "0", "false", "no", "off", "/off", "unchecked"):
        return "/Off"

    return raw if raw.startswith("/") else f"/{raw}"


def _field_metadata_by_name(fields_json):
    by_name = {}
    for field in (fields_json or {}).get("fields") or []:
        name = field.get("name")
        if name:
            by_name[str(name)] = field
    return by_name


def _build_pdf_field_values(payload, fields_json):
    field_meta = _field_metadata_by_name(fields_json)
    field_names = set(field_meta.keys())

    if not field_names:
        return {str(key): _stringify_pdf_value(value) for key, value in (payload or {}).items()}, [], []

    values = {}
    skipped = []

    for key, value in (payload or {}).items():
        field_name = str(key)
        if field_name not in field_names:
            skipped.append(field_name)
            continue

        meta = field_meta.get(field_name) or {}
        field_type = str(meta.get("type") or "")

        if field_type == "/Btn":
            values[field_name] = _normalize_checkbox_value(value, meta.get("states") or [])
        else:
            values[field_name] = _stringify_pdf_value(value)

    missing_in_payload = sorted(name for name in field_names if name not in values)

    return values, skipped, missing_in_payload


def _build_output_pdf_path(export_data):
    document_template = export_data.get("document_template") or {}
    expediente = export_data.get("expediente") or {}
    output = export_data.get("output") or {}

    output_dir_raw = str(output.get("directory") or "").strip()
    if not output_dir_raw:
        raise ValueError("El export de payload no contiene directorio de salida")

    output_dir = BASE_DIR / output_dir_raw.replace("\\", "/")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    template_code = _safe_filename(document_template.get("codigo"))
    expediente_part = _safe_filename((expediente or {}).get("numero_expediente")) if expediente else "GENERAL"

    return output_dir / f"{template_code}_{expediente_part}_{timestamp}.pdf"


def _set_need_appearances(writer):
    try:
        writer.set_need_appearances_writer(True)
        return
    except Exception:
        pass

    try:
        catalog = writer._root_object
        acro_form = catalog.get("/AcroForm")
        if acro_form:
            acro_form.update({NameObject("/NeedAppearances"): BooleanObject(True)})
    except Exception:
        pass


def _update_pdf_pages(writer, pdf_values, flatten=False):
    """
    pypdf actualiza correctamente cuando se llama página por página.

    En algunos AcroForm oficiales, pasar writer.pages completo produce el aviso
    "No fields to update on this page" y el PDF queda visualmente vacío aunque
    el servicio tenga valores en memoria.
    """
    updated_pages = 0
    errors = []

    for page_index, page in enumerate(writer.pages, start=1):
        try:
            before = str(page)
            writer.update_page_form_field_values(
                page,
                pdf_values,
                auto_regenerate=True,
                flatten=bool(flatten),
            )
            after = str(page)
            # No todos los objetos cambian de forma detectable con str(),
            # pero este contador sirve como trazabilidad aproximada.
            if before != after:
                updated_pages += 1
        except Exception as exc:
            errors.append(f"Página {page_index}: {exc}")

    _set_need_appearances(writer)

    return {
        "updated_pages": updated_pages,
        "page_update_errors": errors,
    }


def fill_pdf_from_template(document_template_id, expediente_id=None, auto_build_snapshot=True, flatten=False):
    """
    Rellena un PDF AcroForm desde una plantilla documental y su mapper.

    Flujo:
    document_template PDF -> mapper_destino -> payload -> AcroForm PDF

    No toca Box.
    No toca Mercurio.
    No modifica expedientes.
    """
    document_template_service.initialize_document_templates_schema()

    template = document_template_service.get_document_template(document_template_id)
    if not template:
        raise ValueError(f"No existe document_template_id={document_template_id}")

    if not int(template.get("activo") or 0):
        raise ValueError("La plantilla documental está inactiva.")

    if str(template.get("template_type") or "").strip().lower() != "pdf":
        raise ValueError("La plantilla documental no es de tipo pdf.")

    template_path = _resolve_project_path(template.get("template_path"))
    if not template_path.exists():
        raise FileNotFoundError(f"No existe el PDF de plantilla: {_relative_path(template_path)}")

    export_data = document_generation_service.export_document_payload(
        document_template_id,
        expediente_id=expediente_id,
        auto_build_snapshot=auto_build_snapshot,
    )

    payload = export_data.get("payload") or {}
    fields_json = _load_fields_json(template)
    pdf_values, skipped_payload_fields, missing_pdf_fields = _build_pdf_field_values(payload, fields_json)

    if not pdf_values:
        raise ValueError(
            "No hay campos PDF para rellenar. Revisa que el mapper use nombres reales del PDF "
            "(por ejemplo Texto1, Texto2...) y que fields_json_path esté configurado."
        )

    reader = PdfReader(str(template_path))
    writer = PdfWriter()
    writer.append(reader)
    _set_need_appearances(writer)

    update_info = _update_pdf_pages(writer, pdf_values, flatten=flatten)

    output_pdf_path = _build_output_pdf_path(export_data)
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with output_pdf_path.open("wb") as fh:
        writer.write(fh)

    inbox_item = None
    try:
        expediente = export_data.get("expediente") or {}
        document_template = export_data.get("document_template") or {}
        inbox_item = document_inbox_service.import_file_to_inbox(
            str(output_pdf_path),
            source_type="crm_generated_pdf",
            source_label="Documento PDF generado por CRM",
            notes="Documento generado automáticamente desde plantilla PDF del CRM.",
            client_id=expediente.get("client_id") or expediente.get("cliente_id"),
            expedient_id=expediente.get("id") or expediente.get("expediente_id"),
            metadata={
                "generated_by": "crm_document_generation",
                "generation_type": "pdf_acroform",
                "document_template_id": document_template.get("id"),
                "document_template_code": document_template.get("codigo"),
                "document_template_name": document_template.get("nombre"),
                "output_path": str(output_pdf_path),
                "output_relative_path": _relative_path(output_pdf_path),
                "payload_json_path": (export_data.get("output") or {}).get("json_path"),
                "flatten": bool(flatten),
            },
        )
    except Exception as exc:
        inbox_item = {
            "registration_error": str(exc),
            "source": "pdf_fill_service",
        }

    result = {
        "generated_at": _now_iso(),
        "generation_type": "pdf_acroform",
        "document_template": _template_public(template),
        "expediente": export_data.get("expediente"),
        "mapper": export_data.get("mapper"),
        "snapshot": export_data.get("snapshot"),
        "payload": payload,
        "validation": export_data.get("validation") or {},
        "empty_fields": export_data.get("empty_fields") or [],
        "summary": export_data.get("summary") or {},
        "pdf": {
            "template_path": _relative_path(template_path),
            "fields_json_path": template.get("fields_json_path") or "",
            "pdf_path": _relative_path(output_pdf_path),
            "filled_fields": sorted(pdf_values.keys()),
            "filled_count": len(pdf_values),
            "skipped_payload_fields": sorted(skipped_payload_fields),
            "skipped_payload_count": len(skipped_payload_fields),
            "missing_pdf_fields": missing_pdf_fields,
            "missing_pdf_count": len(missing_pdf_fields),
            "flatten": bool(flatten),
            "updated_pages": update_info.get("updated_pages", 0),
            "page_update_errors": update_info.get("page_update_errors", []),
        },
        "output": {
            "directory": export_data.get("output", {}).get("directory"),
            "json_path": export_data.get("output", {}).get("json_path"),
            "pdf_path": _relative_path(output_pdf_path),
            "format": "pdf",
        },
        "inbox_item": inbox_item,
    }

    return result


def fill_pdf_from_template_code(codigo, expediente_id=None, auto_build_snapshot=True, flatten=False):
    template = document_template_service.get_document_template_by_code(codigo, active_only=True)
    if not template:
        raise ValueError(f"No existe plantilla documental activa con código={codigo}")

    return fill_pdf_from_template(
        template["id"],
        expediente_id=expediente_id,
        auto_build_snapshot=auto_build_snapshot,
        flatten=flatten,
    )
