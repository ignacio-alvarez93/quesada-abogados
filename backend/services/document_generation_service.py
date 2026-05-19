import json
from datetime import datetime
from pathlib import Path

from backend.services import document_template_service
from backend.services import expedient_service
from backend.services import form_mapper_admin_service
from backend.services import form_mapper_service
from backend.services import mapper_preview_service


BASE_DIR = Path(__file__).resolve().parents[2]


def _normalize_code(value):
    return str(value or "").strip().upper().replace(" ", "_")


def _safe_filename(value):
    raw = _normalize_code(value)
    safe = []
    for char in raw:
        if char.isalnum() or char in ("_", "-"):
            safe.append(char)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "DOCUMENTO"


def _relative_path(path):
    try:
        return str(Path(path).resolve().relative_to(BASE_DIR)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _get_expediente_public_info(expediente_id):
    if expediente_id in (None, "", "None"):
        return None

    expediente = expedient_service.get_expediente(expediente_id)
    if not expediente:
        raise ValueError(f"No existe expediente id={expediente_id}")

    return {
        "id": expediente.get("id"),
        "numero_expediente": expediente.get("numero_expediente"),
        "numero_expediente_mercurio": expediente.get("numero_expediente_mercurio"),
        "cliente_id": expediente.get("cliente_id"),
        "cliente_nombre": " ".join(
            part
            for part in [
                expediente.get("cliente_nombre"),
                expediente.get("cliente_primer_apellido"),
                expediente.get("cliente_segundo_apellido"),
            ]
            if part
        ).strip(),
        "tipo_expediente_id": expediente.get("tipo_expediente_id"),
        "tipo_expediente_nombre": expediente.get("tipo_expediente_nombre"),
        "subtipo_expediente_id": expediente.get("subtipo_expediente_id"),
        "subtipo_expediente_nombre": expediente.get("subtipo_expediente_nombre"),
    }


def _get_active_mapper_template_by_code(codigo):
    normalized = _normalize_code(codigo)
    for template in form_mapper_admin_service.list_mapper_templates(active_only=True):
        if _normalize_code(template.get("codigo")) == normalized:
            return template
    return None


def _build_static_or_empty_preview(document_template, expediente_id=None):
    """
    Fallback para plantillas generales sin expediente.

    Permite exportar payload para mappers con valores estáticos.
    Si el mapper usa rutas de snapshot, esas claves quedarán vacías y la validación
    las marcará si son obligatorias.
    """
    mapper_code = document_template.get("mapper_destino") or document_template.get("codigo")
    mapper_template = _get_active_mapper_template_by_code(mapper_code)
    if not mapper_template:
        raise ValueError(
            f"No existe mapper activo con código={_normalize_code(mapper_code)} "
            "para esta plantilla documental."
        )

    payload_result = form_mapper_service.build_payload_from_template({}, mapper_template)
    payload = payload_result.get("payload") or {}
    validation = payload_result.get("validation") or {"valid": False, "errors": ["Validación no disponible"]}
    empty_fields = []
    for key, value in payload.items():
        if value is None:
            empty_fields.append(key)
        elif isinstance(value, str) and not value.strip():
            empty_fields.append(key)
        elif isinstance(value, (list, dict)) and not value:
            empty_fields.append(key)

    return {
        "preview_generated_at": datetime.now().isoformat(timespec="seconds"),
        "expediente_id": expediente_id,
        "snapshot": {
            "source": "empty_context",
            "generated_in_memory": True,
            "id": None,
            "version": None,
            "validated": None,
            "created_at": None,
            "source_hash": None,
        },
        "template": {
            "id": mapper_template.get("id"),
            "codigo": mapper_template.get("codigo"),
            "nombre": mapper_template.get("nombre"),
            "tipo_destino": mapper_template.get("tipo_destino"),
            "version": mapper_template.get("version"),
            "activo": mapper_template.get("activo"),
            "mapper": form_mapper_service.compose_template_mapper(mapper_template).get("mapper") or {},
            "required_fields": form_mapper_service.compose_template_mapper(mapper_template).get("required_fields") or [],
        },
        "payload": payload,
        "validation": validation,
        "empty_fields": empty_fields,
        "summary": {
            "payload_fields": len(payload),
            "empty_fields": len(empty_fields),
            "required_errors": len(validation.get("errors") or []),
            "valid": bool(validation.get("valid")),
        },
        "document_template": _document_template_public_info(document_template),
        "mapper_match": {
            "mode": "mapper_codigo_empty_context",
            "mapper_template_id": mapper_template.get("id"),
            "mapper_codigo": mapper_template.get("codigo"),
        },
    }


def _document_template_public_info(template):
    return {
        "id": template.get("id"),
        "codigo": template.get("codigo"),
        "nombre": template.get("nombre"),
        "nombre_oficial": template.get("nombre_oficial"),
        "descripcion": template.get("descripcion"),
        "categoria": template.get("categoria"),
        "tipo_destino": template.get("tipo_destino"),
        "template_type": template.get("template_type"),
        "template_path": template.get("template_path"),
        "fields_json_path": template.get("fields_json_path"),
        "metadata_json_path": template.get("metadata_json_path"),
        "mapper_destino": template.get("mapper_destino"),
        "requiere_expediente": template.get("requiere_expediente"),
        "activo": template.get("activo"),
        "orden": template.get("orden"),
    }


def _build_preview(document_template, expediente_id=None, auto_build_snapshot=True):
    requires_expediente = int(document_template.get("requiere_expediente") or 0) == 1
    categoria = _normalize_code(document_template.get("categoria"))

    if categoria == "EX" and not expediente_id:
        raise ValueError("Las plantillas EX requieren expediente para exportar payload.")

    if requires_expediente and not expediente_id:
        raise ValueError("Esta plantilla requiere expediente para exportar payload.")

    if expediente_id:
        return mapper_preview_service.preview_document_template_for_expedient(
            document_template["id"],
            expediente_id,
            auto_build_snapshot=auto_build_snapshot,
        )

    return _build_static_or_empty_preview(document_template, expediente_id=None)


def _build_output_json_path(document_template, output_dir, expediente_numero=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    template_code = _safe_filename(document_template.get("codigo"))
    expediente_part = _safe_filename(expediente_numero) if expediente_numero else "GENERAL"
    filename = f"{template_code}_{expediente_part}_payload_{timestamp}.json"
    return Path(output_dir) / filename


def export_document_payload(document_template_id, expediente_id=None, auto_build_snapshot=True):
    """
    Exporta el payload normalizado de una plantilla documental a JSON.

    No genera DOCX/PDF.
    No toca Box.
    No toca Mercurio.
    No modifica expedientes.

    Reglas de salida:
    - categoria EX -> exports/ex_forms/<numero_expediente>/
    - requiere_expediente=1 -> exports/documents/expedientes/<numero_expediente>/
    - requiere_expediente=0 -> exports/documents/general/
    """
    document_template_service.initialize_document_templates_schema()

    document_template = document_template_service.get_document_template(document_template_id)
    if not document_template:
        raise ValueError(f"No existe document_template_id={document_template_id}")

    if not int(document_template.get("activo") or 0):
        raise ValueError("La plantilla documental está inactiva.")

    expediente = _get_expediente_public_info(expediente_id) if expediente_id else None
    expediente_numero = expediente.get("numero_expediente") if expediente else None

    preview = _build_preview(
        document_template,
        expediente_id=expediente_id,
        auto_build_snapshot=auto_build_snapshot,
    )

    output_dir = document_template_service.get_generation_output_dir(
        document_template,
        expediente_numero=expediente_numero,
    )
    json_path = _build_output_json_path(
        document_template,
        output_dir,
        expediente_numero=expediente_numero,
    )

    export_data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generation_type": "payload_json",
        "document_template": _document_template_public_info(document_template),
        "expediente": expediente,
        "mapper": {
            "mapper_template": preview.get("template"),
            "mapper_match": preview.get("mapper_match"),
        },
        "snapshot": preview.get("snapshot"),
        "payload": preview.get("payload") or {},
        "validation": preview.get("validation") or {},
        "empty_fields": preview.get("empty_fields") or [],
        "summary": preview.get("summary") or {},
        "output": {
            "directory": _relative_path(output_dir),
            "json_path": _relative_path(json_path),
            "format": "json",
        },
    }

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return export_data


def export_document_payload_by_code(codigo, expediente_id=None, auto_build_snapshot=True):
    template = document_template_service.get_document_template_by_code(codigo, active_only=True)
    if not template:
        raise ValueError(f"No existe plantilla documental activa con código={codigo}")

    return export_document_payload(
        template["id"],
        expediente_id=expediente_id,
        auto_build_snapshot=auto_build_snapshot,
    )
