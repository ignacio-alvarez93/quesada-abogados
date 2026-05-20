import copy


STATIC_VALUE_PREFIX = "__static__:"
EQUALS_VALUE_PREFIX = "__equals__:"


def deep_get(data, path, default=""):
    current = data

    for part in str(path or "").split("."):
        if current is None:
            return default

        if isinstance(current, dict):
            current = current.get(part)
        else:
            return default

    return current if current is not None else default


def normalize_string(value):
    return str(value or "").strip()


def _normalize_equals_value(value):
    """
    Normaliza valores para comparaciones declarativas del mapper.

    Evita que diferencias habituales de mayúsculas, espacios o acentos rompan
    reglas tipo:
        "__equals__:cliente.estado_civil:soltero"
    """
    text = str(value or "").strip().lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
        "ñ": "n",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return " ".join(text.split())


def _parse_equals_expression(expression):
    """
    Parsea:
        __equals__:ruta.snapshot:valor esperado

    Permite que el valor esperado contenga ":".
    """
    body = expression[len(EQUALS_VALUE_PREFIX):]
    if ":" not in body:
        return "", ""
    source_path, expected_value = body.split(":", 1)
    return source_path.strip(), expected_value.strip()


def resolve_mapping_source(flat_snapshot, source_path):
    """
    Resuelve el origen de una regla de mapping.

    Soporta:
    - rutas del snapshot: "cliente.nombre"
    - valores estáticos: "__static__:Residencia"
    - condiciones booleanas: "__equals__:cliente.estado_civil:soltero"
    - literales no string

    __equals__ devuelve booleano:
    - True si el valor del snapshot coincide con el esperado.
    - False en caso contrario.

    Esto permite marcar casillas PDF:
        "Casilla de verificación7": "__equals__:cliente.estado_civil:soltero"
    """
    if source_path is None:
        return ""

    if not isinstance(source_path, str):
        return source_path

    if source_path.startswith(STATIC_VALUE_PREFIX):
        return source_path[len(STATIC_VALUE_PREFIX):]

    if source_path.startswith(EQUALS_VALUE_PREFIX):
        compare_path, expected_value = _parse_equals_expression(source_path)
        current_value = flat_snapshot.get(compare_path, "")
        return _normalize_equals_value(current_value) == _normalize_equals_value(expected_value)

    return flat_snapshot.get(source_path, "")


def build_flat_snapshot_map(snapshot):
    """
    Convierte snapshot jerárquico en mapa plano reutilizable.

    Ejemplo:
    cliente.nombre -> "Juan"
    expediente.numero_expediente -> "EXP-2026-0001"
    """

    result = {}

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_prefix = f"{prefix}.{key}" if prefix else str(key)
                walk(value, new_prefix)

        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                new_prefix = f"{prefix}.{idx}"
                walk(value, new_prefix)

        else:
            result[prefix] = obj

    walk(snapshot)
    return result


def get_snapshot_field_paths(snapshot):
    """
    Devuelve únicamente las rutas disponibles del snapshot.

    Ejemplo:
    [
        "cliente.nombre",
        "cliente.nie",
        "datos_especificos.salario"
    ]
    """

    flat = build_flat_snapshot_map(snapshot)
    return sorted(flat.keys())


def apply_field_mapping(snapshot, mapping):
    """
    mapping:

    {
        "mercurio_nombre": "cliente.nombre",
        "mercurio_nie": "cliente.nie"
    }
    """

    flat = build_flat_snapshot_map(snapshot)

    result = {}

    for target_field, source_path in (mapping or {}).items():
        result[target_field] = resolve_mapping_source(flat, source_path)

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
        value = payload.get(field)

        if value is None:
            errors.append(f"Campo obligatorio vacío: {field}")
            continue

        if isinstance(value, str) and not value.strip():
            errors.append(f"Campo obligatorio vacío: {field}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "database" / "form_mapper_schema.sql"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_form_mapper_schema():
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def create_mapper_template(data):
    initialize_form_mapper_schema()

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO form_mapper_templates (
                codigo,
                nombre,
                tipo_destino,
                activo,
                tipo_expediente_id,
                subtipo_expediente_id,
                mapper_json,
                required_fields_json,
                version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("codigo"),
                data.get("nombre"),
                data.get("tipo_destino"),
                int(data.get("activo", 1)),
                data.get("tipo_expediente_id"),
                data.get("subtipo_expediente_id"),
                json.dumps(data.get("mapper") or {}, ensure_ascii=False),
                json.dumps(data.get("required_fields") or [], ensure_ascii=False),
                int(data.get("version", 1)),
            ),
        )

        conn.commit()
        return cur.lastrowid


def get_mapper_template(tipo_destino, tipo_expediente_id=None, subtipo_expediente_id=None):
    initialize_form_mapper_schema()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM form_mapper_templates
            WHERE activo = 1
              AND tipo_destino = ?
              AND (
                    subtipo_expediente_id = ?
                    OR (
                        subtipo_expediente_id IS NULL
                        AND tipo_expediente_id = ?
                    )
                  )
            ORDER BY
                CASE
                    WHEN subtipo_expediente_id IS NOT NULL THEN 1
                    ELSE 2
                END,
                version DESC
            LIMIT 1
            """,
            (
                tipo_destino,
                subtipo_expediente_id,
                tipo_expediente_id,
            ),
        ).fetchone()

    if not row and tipo_expediente_id is None and subtipo_expediente_id is None:
        # Fallback mapper global:
        # cuando no hay tipo/subtipo, SQLite no compara NULL con "=".
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM form_mapper_templates
                WHERE activo = 1
                  AND tipo_destino = ?
                  AND tipo_expediente_id IS NULL
                  AND subtipo_expediente_id IS NULL
                ORDER BY version DESC
                LIMIT 1
                """,
                (tipo_destino,),
            ).fetchone()

    if not row:
        return None

    item = dict(row)

    item["mapper"] = json.loads(item.get("mapper_json") or "{}")
    item["required_fields"] = json.loads(item.get("required_fields_json") or "[]")
    item["block_codes"] = json.loads(item.get("block_codes_json") or "[]")

    return item


def compose_template_mapper(template):
    """
    Compone mapper final usando:
    - bloques reutilizables
    - mapper propio template

    Prioridad:
    mapper del template sobrescribe bloques.
    """

    try:
        from backend.services import form_mapper_admin_service as admin_service
    except Exception:
        admin_service = None

    final_mapper = {}
    final_required_fields = []

    block_codes = template.get("block_codes") or []

    if admin_service and block_codes:
        block_result = admin_service.build_mapper_from_blocks(block_codes)

        final_mapper.update(block_result.get("mapper") or {})

        for field in block_result.get("required_fields") or []:
            if field not in final_required_fields:
                final_required_fields.append(field)

    final_mapper.update(template.get("mapper") or {})

    for field in template.get("required_fields") or []:
        if field not in final_required_fields:
            final_required_fields.append(field)

    return {
        "mapper": final_mapper,
        "required_fields": final_required_fields,
    }



def build_payload_from_template(snapshot, template):
    if not template:
        raise ValueError("Template mapper no encontrado")

    composed = compose_template_mapper(template)

    payload = apply_field_mapping(
        snapshot,
        composed.get("mapper") or {},
    )

    validation = validate_required_fields(
        payload,
        composed.get("required_fields") or [],
    )

    return {
        "payload": payload,
        "validation": validation,
        "template": template,
    }


def build_payload_for_destination(
    snapshot,
    tipo_destino,
    tipo_expediente_id=None,
    subtipo_expediente_id=None,
):
    template = get_mapper_template(
        tipo_destino,
        tipo_expediente_id,
        subtipo_expediente_id,
    )

    return build_payload_from_template(snapshot, template)
