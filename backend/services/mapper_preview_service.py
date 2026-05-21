import json
from datetime import datetime

from backend.services import expedient_service
from backend.services import expedient_snapshot_service
from backend.services import form_mapper_admin_service
from backend.services import form_mapper_service


def _safe_int(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _json_loads(value, fallback):
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _normalize_destination(value):
    return str(value or "").strip().upper().replace(" ", "_")


def _empty_payload_fields(payload):
    """Devuelve campos del payload que han quedado vacíos."""
    empty = []
    for key, value in (payload or {}).items():
        if value is None:
            empty.append(key)
        elif isinstance(value, str) and not value.strip():
            empty.append(key)
        elif isinstance(value, (list, dict)) and not value:
            empty.append(key)
    return empty


def _snapshot_info(snapshot_record, generated_in_memory=False):
    if not snapshot_record:
        return {
            "source": "memory",
            "generated_in_memory": True,
            "id": None,
            "version": None,
            "validated": None,
            "created_at": None,
            "source_hash": None,
        }
    return {
        "source": "latest_snapshot",
        "generated_in_memory": bool(generated_in_memory),
        "id": snapshot_record.get("id"),
        "version": snapshot_record.get("version"),
        "validated": snapshot_record.get("validated"),
        "created_at": snapshot_record.get("created_at"),
        "source_hash": snapshot_record.get("source_hash"),
    }


def _get_snapshot_for_preview(expediente_id, auto_build=True):
    """
    Obtiene el último snapshot guardado.

    Si no existe y auto_build=True, genera snapshot en memoria sin persistirlo.
    """
    snapshot_record = expedient_snapshot_service.load_latest_snapshot(expediente_id)
    if snapshot_record:
        return snapshot_record.get("snapshot") or {}, snapshot_record, False
    if not auto_build:
        raise ValueError("El expediente no tiene snapshot guardado. Genera un snapshot antes de previsualizar.")
    snapshot = expedient_snapshot_service.build_snapshot(expediente_id)
    return snapshot, None, True


def _template_public_info(template):
    if not template:
        return None
    composed = form_mapper_service.compose_template_mapper(template)
    return {
        "id": template.get("id"),
        "codigo": template.get("codigo"),
        "nombre": template.get("nombre"),
        "tipo_destino": template.get("tipo_destino"),
        "tipo_expediente_id": template.get("tipo_expediente_id"),
        "subtipo_expediente_id": template.get("subtipo_expediente_id"),
        "version": template.get("version"),
        "activo": template.get("activo"),
        "block_codes": template.get("block_codes") or _json_loads(template.get("block_codes_json"), []),
        "mapper": composed.get("mapper") or {},
        "required_fields": composed.get("required_fields") or [],
    }


def _build_preview_result(expediente_id, snapshot, snapshot_record, generated_in_memory, template):
    if not template:
        raise ValueError("Template mapper no encontrado")
    payload_result = form_mapper_service.build_payload_from_template(snapshot, template)
    payload = payload_result.get("payload") or {}
    validation = payload_result.get("validation") or {"valid": False, "errors": ["Validación no disponible"]}
    empty_fields = _empty_payload_fields(payload)
    return {
        "preview_generated_at": datetime.now().isoformat(timespec="seconds"),
        "expediente_id": int(expediente_id),
        "snapshot": _snapshot_info(snapshot_record, generated_in_memory=generated_in_memory),
        "template": _template_public_info(template),
        "payload": payload,
        "validation": validation,
        "empty_fields": empty_fields,
        "summary": {
            "payload_fields": len(payload),
            "empty_fields": len(empty_fields),
            "required_errors": len(validation.get("errors") or []),
            "valid": bool(validation.get("valid")),
        },
    }


def preview_mapper_for_expedient(expediente_id, mapper_template_id, auto_build_snapshot=True):
    """
    Previsualiza un mapper concreto contra un expediente.

    No ejecuta Mercurio, no modifica Box y no presenta nada.
    Solo construye el payload resultante.
    """
    snapshot, snapshot_record, generated_in_memory = _get_snapshot_for_preview(
        expediente_id,
        auto_build=auto_build_snapshot,
    )
    template = form_mapper_admin_service.get_mapper_template(mapper_template_id)
    if not template:
        raise ValueError(f"No existe mapper_template_id={mapper_template_id}")
    return _build_preview_result(
        expediente_id,
        snapshot,
        snapshot_record,
        generated_in_memory,
        template,
    )


def _get_template_for_destination(expediente, tipo_destino):
    """
    Busca mapper para un destino con prioridad:
    1. Mapper específico del subtipo/tipo del expediente.
    2. Mapper general del destino, sin tipo ni subtipo.
    """
    tipo_destino = _normalize_destination(tipo_destino)
    tipo_id = _safe_int(expediente.get("tipo_expediente_id"))
    subtipo_id = _safe_int(expediente.get("subtipo_expediente_id"))
    template = form_mapper_service.get_mapper_template(
        tipo_destino,
        tipo_expediente_id=tipo_id,
        subtipo_expediente_id=subtipo_id,
    )
    if template:
        return template, "specific"
    template = form_mapper_service.get_mapper_template(
        tipo_destino,
        tipo_expediente_id=None,
        subtipo_expediente_id=None,
    )
    if template:
        return template, "general"
    return None, "not_found"


def preview_destination_for_expedient(expediente_id, tipo_destino, auto_build_snapshot=True):
    """
    Previsualiza el payload para un destino, eligiendo automáticamente mapper:
    1. Mapper específico del expediente.
    2. Mapper general del destino.
    """
    expediente = expedient_service.get_expediente(expediente_id)
    if not expediente:
        raise ValueError(f"No existe expediente id={expediente_id}")
    snapshot, snapshot_record, generated_in_memory = _get_snapshot_for_preview(
        expediente_id,
        auto_build=auto_build_snapshot,
    )
    template, match_level = _get_template_for_destination(expediente, tipo_destino)
    if not template:
        raise ValueError(
            f"No existe mapper activo para destino={_normalize_destination(tipo_destino)} "
            f"ni específico del expediente ni general."
        )
    result = _build_preview_result(
        expediente_id,
        snapshot,
        snapshot_record,
        generated_in_memory,
        template,
    )
    result["match_level"] = match_level
    result["destination"] = _normalize_destination(tipo_destino)
    result["expediente"] = {
        "id": expediente.get("id"),
        "numero_expediente": expediente.get("numero_expediente"),
        "tipo_expediente_id": expediente.get("tipo_expediente_id"),
        "tipo_expediente_nombre": expediente.get("tipo_expediente_nombre"),
        "subtipo_expediente_id": expediente.get("subtipo_expediente_id"),
        "subtipo_expediente_nombre": expediente.get("subtipo_expediente_nombre"),
    }
    return result


def preview_mapper_json(expediente_id, mapper_json, required_fields_json=None, auto_build_snapshot=True):
    """
    Previsualiza un mapper ad hoc sin guardarlo en base de datos.
    """
    snapshot, snapshot_record, generated_in_memory = _get_snapshot_for_preview(
        expediente_id,
        auto_build=auto_build_snapshot,
    )
    mapper = _json_loads(mapper_json, {})
    required_fields = _json_loads(required_fields_json, [])
    template = {
        "id": None,
        "codigo": "AD_HOC_PREVIEW",
        "nombre": "Preview ad hoc",
        "tipo_destino": "AD_HOC",
        "tipo_expediente_id": None,
        "subtipo_expediente_id": None,
        "version": 1,
        "activo": 1,
        "mapper": mapper,
        "required_fields": required_fields,
        "block_codes": [],
    }
    return _build_preview_result(
        expediente_id,
        snapshot,
        snapshot_record,
        generated_in_memory,
        template,
    )

def preview_document_template_for_expedient(document_template_id, expediente_id=None, auto_build_snapshot=True):
    """
    Previsualiza el payload de una plantilla documental usando su mapper_destino.

    Función de compatibilidad usada por Settings / generación documental:
    - No modifica expedientes.
    - No genera PDF/DOCX.
    - No toca Box ni Mercurio.
    - Solo resuelve document_template -> mapper_destino -> payload.
    """
    from backend.services import document_template_service

    document_template_service.initialize_document_templates_schema()
    document_template = document_template_service.get_document_template(document_template_id)
    if not document_template:
        raise ValueError(f"No existe document_template_id={document_template_id}")

    mapper_destino = str(
        document_template.get("mapper_destino")
        or document_template.get("codigo")
        or ""
    ).strip()

    if not mapper_destino:
        raise ValueError("La plantilla documental no tiene mapper_destino configurado.")

    requiere_expediente = int(document_template.get("requiere_expediente") or 0)

    if expediente_id in (None, "", "None"):
        if requiere_expediente:
            raise ValueError("Esta plantilla requiere expediente para previsualizar el payload.")
        return {
            "preview_generated_at": datetime.now().isoformat(timespec="seconds"),
            "expediente_id": None,
            "document_template": {
                "id": document_template.get("id"),
                "codigo": document_template.get("codigo"),
                "nombre": document_template.get("nombre"),
                "tipo_destino": document_template.get("tipo_destino"),
                "template_type": document_template.get("template_type"),
                "mapper_destino": mapper_destino,
                "requiere_expediente": document_template.get("requiere_expediente"),
                "activo": document_template.get("activo"),
            },
            "payload": {},
            "validation": {
                "valid": False,
                "errors": ["No hay expediente seleccionado; no se puede construir snapshot."],
            },
            "empty_fields": [],
            "summary": {
                "payload_fields": 0,
                "empty_fields": 0,
                "required_errors": 1,
                "valid": False,
            },
        }

    expediente = expedient_service.get_expediente(int(expediente_id))
    if not expediente:
        raise ValueError(f"No existe expediente id={expediente_id}")

    snapshot, snapshot_record, generated_in_memory = _get_snapshot_for_preview(
        int(expediente_id),
        auto_build=auto_build_snapshot,
    )

    # En plantillas documentales, mapper_destino identifica el CÓDIGO del mapper
    # (por ejemplo EX01), no necesariamente su tipo_destino/canal (PDF, DOCX, MERCURIO).
    # Por eso no usamos preview_destination_for_expedient(mapper_destino), porque eso
    # interpretaría EX01 como tipo_destino=EX01 y no encontraría mappers cuyo canal es PDF.
    tipo_id = _safe_int(expediente.get("tipo_expediente_id"))
    subtipo_id = _safe_int(expediente.get("subtipo_expediente_id"))

    candidates = []
    for template in form_mapper_admin_service.list_mapper_templates(active_only=True):
        if _normalize_destination(template.get("codigo")) != _normalize_destination(mapper_destino):
            continue
        candidates.append(template)

    def _score_template(template):
        t_tipo = _safe_int(template.get("tipo_expediente_id"))
        t_subtipo = _safe_int(template.get("subtipo_expediente_id"))

        if t_tipo == tipo_id and t_subtipo == subtipo_id and t_subtipo is not None:
            return 30
        if t_tipo == tipo_id and t_subtipo is None:
            return 20
        if t_tipo is None and t_subtipo is None:
            return 10
        return -1

    scored = [
        (_score_template(template), template)
        for template in candidates
    ]
    scored = [item for item in scored if item[0] >= 0]
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        raise ValueError(
            f"No existe mapper activo con código={mapper_destino} compatible con el expediente."
        )

    match_score, mapper_template = scored[0]
    result = _build_preview_result(
        int(expediente_id),
        snapshot,
        snapshot_record,
        generated_in_memory,
        mapper_template,
    )
    result["match_level"] = (
        "specific_subtype" if match_score == 30 else
        "specific_type" if match_score == 20 else
        "general"
    )
    result["destination"] = _normalize_destination(document_template.get("tipo_destino"))
    result["mapper_lookup"] = {
        "mode": "code",
        "mapper_destino": mapper_destino,
        "mapper_template_id": mapper_template.get("id"),
        "mapper_codigo": mapper_template.get("codigo"),
        "mapper_tipo_destino": mapper_template.get("tipo_destino"),
    }
    result["expediente"] = {
        "id": expediente.get("id"),
        "numero_expediente": expediente.get("numero_expediente"),
        "tipo_expediente_id": expediente.get("tipo_expediente_id"),
        "tipo_expediente_nombre": expediente.get("tipo_expediente_nombre"),
        "subtipo_expediente_id": expediente.get("subtipo_expediente_id"),
        "subtipo_expediente_nombre": expediente.get("subtipo_expediente_nombre"),
    }
    result["document_template"] = {
        "id": document_template.get("id"),
        "codigo": document_template.get("codigo"),
        "nombre": document_template.get("nombre"),
        "tipo_destino": document_template.get("tipo_destino"),
        "template_type": document_template.get("template_type"),
        "template_path": document_template.get("template_path"),
        "fields_json_path": document_template.get("fields_json_path"),
        "mapper_destino": mapper_destino,
        "requiere_expediente": document_template.get("requiere_expediente"),
        "activo": document_template.get("activo"),
    }
    return result

