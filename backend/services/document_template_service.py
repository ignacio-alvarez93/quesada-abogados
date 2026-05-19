from pathlib import Path

from database.connection import get_connection


BASE_DIR = Path(__file__).resolve().parents[2]
SCHEMA_PATH = BASE_DIR / "database" / "document_templates_schema.sql"

TEMPLATES_DIR = BASE_DIR / "templates"
EX_FORMS_DIR = TEMPLATES_DIR / "ex_forms"
DOCUMENTS_DIR = TEMPLATES_DIR / "documents"

EXPORTS_DIR = BASE_DIR / "exports"
EX_EXPORTS_DIR = EXPORTS_DIR / "ex_forms"
DOCUMENTS_EXPORTS_DIR = EXPORTS_DIR / "documents"
DOCUMENTS_GENERAL_EXPORTS_DIR = DOCUMENTS_EXPORTS_DIR / "general"
DOCUMENTS_EXPEDIENTS_EXPORTS_DIR = DOCUMENTS_EXPORTS_DIR / "expedientes"


def _row_to_dict(row):
    return dict(row) if row else None


def _normalize_code(value):
    return (value or "").strip().upper().replace(" ", "_")


def _normalize_text(value):
    return (value or "").strip()


def _normalize_upper(value, default=""):
    raw = value if value not in (None, "") else default
    return str(raw or "").strip().upper().replace(" ", "_")


def _normalize_relative_path(value):
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return ""

    path = Path(raw)
    if path.is_absolute() or (len(raw) >= 3 and raw[1:3] in (":/", ":\\")):
        raise ValueError("La ruta debe ser relativa, no absoluta")

    parts = [p for p in raw.split("/") if p]
    if any(part == ".." for part in parts):
        raise ValueError("La ruta no puede contener '..'")

    return "/".join(parts)


def ensure_template_directories():
    for directory in [
        EX_FORMS_DIR,
        DOCUMENTS_DIR,
        EX_EXPORTS_DIR,
        DOCUMENTS_GENERAL_EXPORTS_DIR,
        DOCUMENTS_EXPEDIENTS_EXPORTS_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def initialize_document_templates_schema():
    """
    Crea la tabla document_templates y sus índices.
    No inserta catálogo por defecto.
    """
    ensure_template_directories()
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()


def normalize_template_data(data):
    data = data or {}
    codigo = _normalize_code(data.get("codigo"))
    nombre = _normalize_text(data.get("nombre"))
    if not codigo:
        raise ValueError("El código de la plantilla es obligatorio")
    if not nombre:
        raise ValueError("El nombre de la plantilla es obligatorio")

    categoria = _normalize_upper(data.get("categoria"), "GENERAL")
    tipo_destino = _normalize_upper(data.get("tipo_destino"), "DOCUMENTO")
    template_type = _normalize_upper(data.get("template_type"), "docx").lower()
    mapper_destino = _normalize_upper(data.get("mapper_destino") or codigo, codigo)

    return {
        "codigo": codigo,
        "nombre": nombre,
        "nombre_oficial": _normalize_text(data.get("nombre_oficial")),
        "descripcion": _normalize_text(data.get("descripcion")),
        "categoria": categoria,
        "tipo_destino": tipo_destino,
        "template_type": template_type,
        "template_path": _normalize_relative_path(data.get("template_path")),
        "fields_json_path": _normalize_relative_path(data.get("fields_json_path")),
        "metadata_json_path": _normalize_relative_path(data.get("metadata_json_path")),
        "mapper_destino": mapper_destino,
        "requiere_expediente": int(data.get("requiere_expediente", 1)),
        "activo": int(data.get("activo", 1)),
        "orden": int(data.get("orden") or 0),
    }


def list_document_templates(active_only=True, categoria=None, tipo_destino=None, requiere_expediente=None):
    initialize_document_templates_schema()
    sql = "SELECT * FROM document_templates"
    params = []
    conditions = []

    if active_only:
        conditions.append("activo = 1")
    if categoria:
        conditions.append("categoria = ?")
        params.append(_normalize_upper(categoria))
    if tipo_destino:
        conditions.append("tipo_destino = ?")
        params.append(_normalize_upper(tipo_destino))
    if requiere_expediente is not None:
        conditions.append("requiere_expediente = ?")
        params.append(1 if requiere_expediente else 0)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY categoria ASC, orden ASC, nombre ASC"

    with get_connection() as conn:
        return [_row_to_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_document_template(template_id):
    initialize_document_templates_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM document_templates WHERE id = ?",
            (int(template_id),),
        ).fetchone()
        return _row_to_dict(row)


def get_document_template_by_code(codigo, active_only=False):
    initialize_document_templates_schema()
    sql = "SELECT * FROM document_templates WHERE codigo = ?"
    params = [_normalize_code(codigo)]
    if active_only:
        sql += " AND activo = 1"
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
        return _row_to_dict(row)


def get_document_template_by_mapper_destino(mapper_destino, active_only=True):
    initialize_document_templates_schema()
    sql = "SELECT * FROM document_templates WHERE mapper_destino = ?"
    params = [_normalize_upper(mapper_destino)]
    if active_only:
        sql += " AND activo = 1"
    sql += " ORDER BY orden ASC, nombre ASC LIMIT 1"
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
        return _row_to_dict(row)


def create_document_template(data):
    initialize_document_templates_schema()
    item = normalize_template_data(data)
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO document_templates (
                codigo, nombre, nombre_oficial, descripcion,
                categoria, tipo_destino, template_type,
                template_path, fields_json_path, metadata_json_path,
                mapper_destino, requiere_expediente,
                activo, orden
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["codigo"], item["nombre"], item["nombre_oficial"], item["descripcion"],
                item["categoria"], item["tipo_destino"], item["template_type"],
                item["template_path"], item["fields_json_path"], item["metadata_json_path"],
                item["mapper_destino"], item["requiere_expediente"], item["activo"], item["orden"],
            ),
        )
        conn.commit()
        return cur.lastrowid


def update_document_template(template_id, data):
    initialize_document_templates_schema()
    item = normalize_template_data(data)
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE document_templates
            SET codigo = ?, nombre = ?, nombre_oficial = ?, descripcion = ?,
                categoria = ?, tipo_destino = ?, template_type = ?,
                template_path = ?, fields_json_path = ?, metadata_json_path = ?,
                mapper_destino = ?, requiere_expediente = ?, activo = ?, orden = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                item["codigo"], item["nombre"], item["nombre_oficial"], item["descripcion"],
                item["categoria"], item["tipo_destino"], item["template_type"],
                item["template_path"], item["fields_json_path"], item["metadata_json_path"],
                item["mapper_destino"], item["requiere_expediente"], item["activo"], item["orden"],
                int(template_id),
            ),
        )
        conn.commit()

        if cur.rowcount == 0:
            raise ValueError(f"No existe la plantilla documental id={template_id}")


def upsert_document_template(data):
    initialize_document_templates_schema()
    item = normalize_template_data(data)
    existing = get_document_template_by_code(item["codigo"], active_only=False)
    if existing:
        update_document_template(existing["id"], item)
        return existing["id"]
    return create_document_template(item)


def set_document_template_active(template_id, active):
    initialize_document_templates_schema()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE document_templates
            SET activo = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if active else 0, int(template_id)),
        )
        conn.commit()


def delete_document_template(template_id):
    """Borrado lógico para no romper histórico de generaciones futuras."""
    set_document_template_active(template_id, False)


def hard_delete_document_template(template_id):
    """
    Borrado físico para plantillas documentales en fase de configuración.

    Se usa desde Settings porque todavía no hay histórico de generaciones
    dependiente de document_templates. Si en el futuro se crea histórico,
    la UI podrá volver a usar delete_document_template().
    """
    initialize_document_templates_schema()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM document_templates WHERE id = ?",
            (int(template_id),),
        )
        conn.commit()

        if cur.rowcount == 0:
            raise ValueError(f"No existe la plantilla documental id={template_id}")


def seed_document_templates(templates):
    """
    Inserta/actualiza una lista explícita de plantillas.
    No contiene catálogo hardcodeado: el llamador decide qué EX/documentos existen.
    """
    return [upsert_document_template(template) for template in (templates or [])]


def build_default_template_paths(codigo, categoria="GENERAL", template_type="docx"):
    normalized_code = _normalize_code(codigo)
    normalized_categoria = _normalize_upper(categoria)
    normalized_type = _normalize_upper(template_type, "docx").lower()

    if normalized_categoria == "EX":
        base = Path("templates") / "ex_forms" / normalized_code
        extension = "pdf"
    else:
        base = Path("templates") / "documents" / normalized_code
        extension = "docx" if normalized_type in ("docx", "word") else "pdf"

    return {
        "template_path": str(base / f"template.{extension}").replace("\\", "/"),
        "fields_json_path": str(base / "fields.json").replace("\\", "/"),
        "metadata_json_path": str(base / "metadata.json").replace("\\", "/"),
    }


def get_generation_output_dir(template, expediente_numero=None):
    ensure_template_directories()
    categoria = _normalize_upper((template or {}).get("categoria"), "GENERAL")
    requiere_expediente = int((template or {}).get("requiere_expediente", 1))

    if categoria == "EX":
        path = EX_EXPORTS_DIR / str(expediente_numero) if expediente_numero else EX_EXPORTS_DIR
    elif requiere_expediente and expediente_numero:
        path = DOCUMENTS_EXPEDIENTS_EXPORTS_DIR / str(expediente_numero)
    else:
        path = DOCUMENTS_GENERAL_EXPORTS_DIR

    path.mkdir(parents=True, exist_ok=True)
    return str(path)
