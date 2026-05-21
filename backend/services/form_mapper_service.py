import copy
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "database" / "quesada.db"

STATIC_PREFIX = "__static__:"
EQUALS_PREFIX = "__equals__:"
SLICE_PREFIX = "__slice__:"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def _json_loads(value, fallback):
    if value in (None, ""):
        return copy.deepcopy(fallback)
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except Exception:
        return copy.deepcopy(fallback)


def _normalize_destination(value):
    return str(value or "").strip().upper().replace(" ", "_")


def _normalize_code(value):
    return str(value or "").strip().upper().replace(" ", "_")


def _normalize_compare(value):
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip()
    # Estados civiles habituales en formularios: SOLTERO/A, CASADO/A, DIVORCIADO/A.
    text = text.replace("/a", "")
    text = text.replace("/o", "")
    return text


def _safe_int(value):
    if value in (None, "", "None"):
        return None
    try:
        return int(value)
    except Exception:
        return None


def initialize_form_mapper_schema():
    """Inicializa las tablas de mappers si existen sus SQL en database/."""
    schema_paths = [
        BASE_DIR / "database" / "form_mapper_schema.sql",
        BASE_DIR / "database" / "form_mapper_blocks_schema.sql",
    ]
    with _connect() as conn:
        for schema_path in schema_paths:
            if schema_path.exists():
                conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()


def deep_get(data, path, default=""):
    current = data
    for part in str(path or "").split("."):
        if part == "":
            return default
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(part, default)
            continue
        if isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except Exception:
                return default
            continue
        return default
    return current if current is not None else default


def normalize_string(value):
    return str(value or "").strip()


def build_flat_snapshot_map(snapshot):
    result = {}

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_prefix = f"{prefix}.{key}" if prefix else str(key)
                walk(value, new_prefix)
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                new_prefix = f"{prefix}.{idx}" if prefix else str(idx)
                walk(value, new_prefix)
        else:
            result[prefix] = obj

    walk(snapshot or {})
    return result


def get_snapshot_field_paths(snapshot):
    return sorted(build_flat_snapshot_map(snapshot).keys())


def _parse_equals_expression(expression):
    body = str(expression or "")[len(EQUALS_PREFIX):]
    if ":" not in body:
        return body.strip(), ""
    source_path, expected_value = body.split(":", 1)
    return source_path.strip(), expected_value.strip()


def _parse_slice_expression(expression):
    body = str(expression or "")[len(SLICE_PREFIX):]
    parts = body.split(":")
    if len(parts) < 2:
        return body.strip(), None, None

    source_path = parts[0].strip()

    def parse_index(raw):
        raw = str(raw or "").strip()
        if raw == "":
            return None
        return int(raw)

    start = parse_index(parts[1]) if len(parts) >= 2 else None
    end = parse_index(parts[2]) if len(parts) >= 3 else None
    return source_path, start, end


def resolve_mapping_value(snapshot, source_expression):
    if source_expression is None:
        return ""

    if not isinstance(source_expression, str):
        return source_expression

    expression = source_expression.strip()

    if expression.startswith(STATIC_PREFIX):
        return expression[len(STATIC_PREFIX):]

    if expression.startswith(EQUALS_PREFIX):
        source_path, expected = _parse_equals_expression(expression)
        actual = deep_get(snapshot, source_path, "")
        return _normalize_compare(actual) == _normalize_compare(expected)

    if expression.startswith(SLICE_PREFIX):
        source_path, start, end = _parse_slice_expression(expression)
        value = deep_get(snapshot, source_path, "")
        return str(value or "")[start:end]

    return deep_get(snapshot, expression, "")


def apply_field_mapping(snapshot, mapping):
    result = {}
    for target_field, source_path in (mapping or {}).items():
        result[target_field] = resolve_mapping_value(snapshot, source_path)
    return result


def build_mercurio_payload(snapshot, mapper_config):
    return apply_field_mapping(snapshot, mapper_config)


def build_ex_payload(snapshot, mapper_config):
    return apply_field_mapping(snapshot, mapper_config)


def merge_override_data(base_payload, override_data):
    merged = copy.deepcopy(base_payload or {})
    for key, value in (override_data or {}).items():
        merged[key] = value
    return merged


def validate_required_fields(payload, required_fields):
    errors = []
    for field in required_fields or []:
        value = (payload or {}).get(field)
        if value is None:
            errors.append(f"Campo obligatorio vacío: {field}")
            continue
        if isinstance(value, str) and not value.strip():
            errors.append(f"Campo obligatorio vacío: {field}")
        elif isinstance(value, (list, dict)) and not value:
            errors.append(f"Campo obligatorio vacío: {field}")
    return {"valid": len(errors) == 0, "errors": errors}


def _load_mapper_blocks_by_codes(codes):
    normalized_codes = [_normalize_code(code) for code in (codes or []) if _normalize_code(code)]
    if not normalized_codes:
        return []

    initialize_form_mapper_schema()
    placeholders = ",".join("?" for _ in normalized_codes)
    sql = f"""
        SELECT *
        FROM form_mapper_blocks
        WHERE activo = 1 AND codigo IN ({placeholders})
        ORDER BY codigo ASC, version DESC, id ASC
    """
    with _connect() as conn:
        rows = conn.execute(sql, normalized_codes).fetchall()
    return [_dict(row) for row in rows]


def compose_template_mapper(template):
    """
    Compone el mapper final de una plantilla:
    1. Bloques reutilizables asociados.
    2. Reglas propias de la plantilla, que prevalecen sobre los bloques.
    """
    template = template or {}
    mapper = {}
    required_fields = []

    block_codes = template.get("block_codes")
    if block_codes is None:
        block_codes = _json_loads(template.get("block_codes_json"), [])

    for block in _load_mapper_blocks_by_codes(block_codes):
        block_mapper = _json_loads(block.get("mapper_json"), {})
        if isinstance(block_mapper, dict):
            mapper.update(block_mapper)
        for field in _json_loads(block.get("required_fields_json"), []):
            if field not in required_fields:
                required_fields.append(field)

    template_mapper = template.get("mapper")
    if template_mapper is None:
        template_mapper = _json_loads(template.get("mapper_json"), {})
    if isinstance(template_mapper, dict):
        mapper.update(template_mapper)

    template_required = template.get("required_fields")
    if template_required is None:
        template_required = _json_loads(template.get("required_fields_json"), [])
    for field in template_required or []:
        if field not in required_fields:
            required_fields.append(field)

    return {"mapper": mapper, "required_fields": required_fields}


def build_payload_from_template(snapshot, template):
    composed = compose_template_mapper(template)
    payload = apply_field_mapping(snapshot, composed.get("mapper") or {})
    validation = validate_required_fields(payload, composed.get("required_fields") or [])
    return {
        "payload": payload,
        "validation": validation,
        "mapper": composed.get("mapper") or {},
        "required_fields": composed.get("required_fields") or [],
    }


def get_mapper_template(tipo_destino, tipo_expediente_id=None, subtipo_expediente_id=None):
    initialize_form_mapper_schema()
    destino = _normalize_destination(tipo_destino)
    tipo_id = _safe_int(tipo_expediente_id)
    subtipo_id = _safe_int(subtipo_expediente_id)

    params = [destino]
    sql = """
        SELECT *
        FROM form_mapper_templates
        WHERE activo = 1
          AND UPPER(REPLACE(COALESCE(tipo_destino, ''), ' ', '_')) = ?
    """

    if tipo_id is None:
        sql += " AND tipo_expediente_id IS NULL AND subtipo_expediente_id IS NULL"
    else:
        sql += " AND tipo_expediente_id = ?"
        params.append(tipo_id)
        if subtipo_id is None:
            sql += " AND subtipo_expediente_id IS NULL"
        else:
            sql += " AND (subtipo_expediente_id = ? OR subtipo_expediente_id IS NULL)"
            params.append(subtipo_id)

    sql += """
        ORDER BY
            CASE WHEN subtipo_expediente_id IS NOT NULL THEN 0 ELSE 1 END,
            version DESC,
            id DESC
        LIMIT 1
    """

    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return _dict(row)
