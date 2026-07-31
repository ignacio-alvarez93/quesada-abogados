"""
Configuración de requisitos documentales agrupados.

Este servicio introduce el nuevo modelo documental sin sustituir todavía
el sistema legacy basado en config_documentos_requeridos.

Fase actual:
- garantiza el esquema;
- valida tipo y subtipo;
- crea documentos canónicos;
- crea grupos;
- vincula documentos a grupos;
- ofrece consultas administrativas;
- no modifica Box Watch;
- no calcula todavía el estado documental del expediente.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260731_create_grouped_document_requirements.sql"
)

VALID_RULES = {
    "ALL",
    "ANY",
    "AT_LEAST",
    "OPTIONAL",
}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _dict(row):
    return dict(row) if row else None


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _normalize_code(value):
    return (
        str(value or "")
        .strip()
        .upper()
        .replace(" ", "_")
    )


def _normalize_name(value):
    return str(value or "").strip().upper()


def initialize_document_requirement_group_schema():
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"No existe el schema documental: {SCHEMA_PATH}"
        )

    with _connection() as conn:
        conn.executescript(
            SCHEMA_PATH.read_text(encoding="utf-8")
        )


def _validate_type_and_subtype(
    conn,
    tipo_expediente_id,
    subtipo_expediente_id=None,
):
    tipo_id = _int_or_none(tipo_expediente_id)
    subtipo_id = _int_or_none(subtipo_expediente_id)

    if tipo_id is None:
        raise ValueError("Selecciona un tipo de expediente")

    tipo = conn.execute(
        """
        SELECT id, codigo, nombre, activo
        FROM config_tipos_expediente
        WHERE id = ?
        """,
        (tipo_id,),
    ).fetchone()

    if not tipo:
        raise ValueError(
            "El tipo de expediente seleccionado no existe"
        )

    if int(tipo["activo"] or 0) != 1:
        raise ValueError(
            "El tipo de expediente seleccionado está inactivo"
        )

    if subtipo_id is None:
        return dict(tipo), None

    subtipo = conn.execute(
        """
        SELECT
            id,
            tipo_expediente_id,
            codigo,
            nombre,
            activo
        FROM config_subtipos_expediente
        WHERE id = ?
        """,
        (subtipo_id,),
    ).fetchone()

    if not subtipo:
        raise ValueError(
            "El subtipo de expediente seleccionado no existe"
        )

    if int(subtipo["activo"] or 0) != 1:
        raise ValueError(
            "El subtipo de expediente seleccionado está inactivo"
        )

    if int(subtipo["tipo_expediente_id"]) != tipo_id:
        raise ValueError(
            "El subtipo seleccionado no pertenece al tipo de expediente"
        )

    return dict(tipo), dict(subtipo)


def _normalize_rule(rule, minimum):
    normalized_rule = _normalize_code(rule or "ALL")

    if normalized_rule not in VALID_RULES:
        raise ValueError(
            "Regla documental no válida. "
            "Usa ALL, ANY, AT_LEAST u OPTIONAL"
        )

    minimum = int(minimum or 0)

    if normalized_rule == "ALL":
        minimum = 0

    elif normalized_rule == "ANY":
        minimum = 1

    elif normalized_rule == "AT_LEAST":
        if minimum < 1:
            raise ValueError(
                "AT_LEAST exige un mínimo de documentos igual o mayor que 1"
            )

    elif normalized_rule == "OPTIONAL":
        minimum = 0

    return normalized_rule, minimum


def create_document_catalog(data):
    initialize_document_requirement_group_schema()

    code = _normalize_code(
        data.get("codigo") or data.get("nombre")
    )
    name = _normalize_name(data.get("nombre"))
    description = str(data.get("descripcion") or "").strip()
    category = _normalize_code(data.get("categoria"))
    active = int(data.get("activo", 1))

    if not code:
        raise ValueError("El código documental es obligatorio")

    if not name:
        raise ValueError("El nombre documental es obligatorio")

    with _connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO config_documentos_catalogo (
                codigo,
                nombre,
                descripcion,
                categoria,
                activo
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                code,
                name,
                description,
                category or None,
                active,
            ),
        )
        return cursor.lastrowid


def list_document_catalog(active_only=False):
    initialize_document_requirement_group_schema()

    sql = """
        SELECT *
        FROM config_documentos_catalogo
    """
    params = []

    if active_only:
        sql += " WHERE activo = ?"
        params.append(1)

    sql += " ORDER BY nombre ASC, id ASC"

    with _connection() as conn:
        return [
            _dict(row)
            for row in conn.execute(sql, params).fetchall()
        ]


def create_requirement_group(data):
    initialize_document_requirement_group_schema()

    tipo_id = _int_or_none(data.get("tipo_expediente_id"))
    subtipo_id = _int_or_none(
        data.get("subtipo_expediente_id")
    )
    code = _normalize_code(
        data.get("codigo") or data.get("nombre")
    )
    name = _normalize_name(data.get("nombre"))
    description = str(data.get("descripcion") or "").strip()
    rule, minimum = _normalize_rule(
        data.get("regla_cumplimiento"),
        data.get("minimo_documentos"),
    )
    order = int(data.get("orden") or 0)
    active = int(data.get("activo", 1))

    if not code:
        raise ValueError("El código del grupo es obligatorio")

    if not name:
        raise ValueError("El nombre del grupo es obligatorio")

    with _connection() as conn:
        _validate_type_and_subtype(
            conn,
            tipo_id,
            subtipo_id,
        )

        cursor = conn.execute(
            """
            INSERT INTO config_grupos_requisitos_documentales (
                tipo_expediente_id,
                subtipo_expediente_id,
                codigo,
                nombre,
                descripcion,
                regla_cumplimiento,
                minimo_documentos,
                orden,
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tipo_id,
                subtipo_id,
                code,
                name,
                description,
                rule,
                minimum,
                order,
                active,
            ),
        )
        return cursor.lastrowid


def add_document_to_group(
    grupo_id,
    documento_catalogo_id,
    *,
    orden=0,
    activo=1,
):
    initialize_document_requirement_group_schema()

    with _connection() as conn:
        group = conn.execute(
            """
            SELECT id
            FROM config_grupos_requisitos_documentales
            WHERE id = ?
            """,
            (int(grupo_id),),
        ).fetchone()

        if not group:
            raise ValueError(
                "El grupo documental seleccionado no existe"
            )

        document = conn.execute(
            """
            SELECT id, activo
            FROM config_documentos_catalogo
            WHERE id = ?
            """,
            (int(documento_catalogo_id),),
        ).fetchone()

        if not document:
            raise ValueError(
                "El documento de catálogo seleccionado no existe"
            )

        if int(document["activo"] or 0) != 1:
            raise ValueError(
                "El documento de catálogo seleccionado está inactivo"
            )

        cursor = conn.execute(
            """
            INSERT INTO config_grupo_requisito_documentos (
                grupo_id,
                documento_catalogo_id,
                orden,
                activo
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                int(grupo_id),
                int(documento_catalogo_id),
                int(orden or 0),
                int(activo),
            ),
        )
        return cursor.lastrowid


def list_requirement_groups(
    tipo_expediente_id=None,
    subtipo_expediente_id=None,
    active_only=False,
):
    initialize_document_requirement_group_schema()

    sql = """
        SELECT
            g.*,
            t.codigo AS tipo_expediente_codigo,
            t.nombre AS tipo_expediente_nombre,
            s.codigo AS subtipo_expediente_codigo,
            s.nombre AS subtipo_expediente_nombre,
            COUNT(o.id) AS total_opciones
        FROM config_grupos_requisitos_documentales g
        JOIN config_tipos_expediente t
          ON t.id = g.tipo_expediente_id
        LEFT JOIN config_subtipos_expediente s
          ON s.id = g.subtipo_expediente_id
        LEFT JOIN config_grupo_requisito_documentos o
          ON o.grupo_id = g.id
         AND o.activo = 1
    """
    conditions = []
    params = []

    if tipo_expediente_id:
        conditions.append("g.tipo_expediente_id = ?")
        params.append(int(tipo_expediente_id))

    if subtipo_expediente_id:
        conditions.append(
            """
            (
                g.subtipo_expediente_id IS NULL
                OR g.subtipo_expediente_id = ?
            )
            """
        )
        params.append(int(subtipo_expediente_id))

    if active_only:
        conditions.append("g.activo = 1")

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += """
        GROUP BY g.id
        ORDER BY
            t.nombre ASC,
            COALESCE(s.nombre, ''),
            g.orden ASC,
            g.nombre ASC
    """

    with _connection() as conn:
        return [
            _dict(row)
            for row in conn.execute(sql, params).fetchall()
        ]


def get_requirement_group(group_id):
    initialize_document_requirement_group_schema()

    with _connection() as conn:
        group = _dict(
            conn.execute(
                """
                SELECT
                    g.*,
                    t.nombre AS tipo_expediente_nombre,
                    s.nombre AS subtipo_expediente_nombre
                FROM config_grupos_requisitos_documentales g
                JOIN config_tipos_expediente t
                  ON t.id = g.tipo_expediente_id
                LEFT JOIN config_subtipos_expediente s
                  ON s.id = g.subtipo_expediente_id
                WHERE g.id = ?
                """,
                (int(group_id),),
            ).fetchone()
        )

        if not group:
            return None

        group["documentos"] = [
            _dict(row)
            for row in conn.execute(
                """
                SELECT
                    o.*,
                    d.codigo AS documento_codigo,
                    d.nombre AS documento_nombre,
                    d.categoria AS documento_categoria
                FROM config_grupo_requisito_documentos o
                JOIN config_documentos_catalogo d
                  ON d.id = o.documento_catalogo_id
                WHERE o.grupo_id = ?
                ORDER BY o.orden ASC, d.nombre ASC
                """,
                (int(group_id),),
            ).fetchall()
        ]

        return group


def validate_requirement_group_readiness(group_id):
    """
    Valida que un grupo activo pueda evaluarse realmente.

    No impide guardar grupos incompletos durante su configuración.
    Debe utilizarse antes de activar el nuevo motor documental o
    publicar una configuración para expedientes.
    """
    initialize_document_requirement_group_schema()

    with _connection() as conn:
        group = conn.execute(
            """
            SELECT
                id,
                regla_cumplimiento,
                minimo_documentos,
                activo
            FROM config_grupos_requisitos_documentales
            WHERE id = ?
            """,
            (int(group_id),),
        ).fetchone()

        if not group:
            raise ValueError(
                "El grupo documental seleccionado no existe"
            )

        option_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM config_grupo_requisito_documentos o
            JOIN config_documentos_catalogo d
              ON d.id = o.documento_catalogo_id
            WHERE o.grupo_id = ?
              AND o.activo = 1
              AND d.activo = 1
            """,
            (int(group_id),),
        ).fetchone()[0]

        rule = _normalize_code(
            group["regla_cumplimiento"]
        )
        minimum = int(group["minimo_documentos"] or 0)

        errors = []

        if rule in {"ALL", "ANY", "AT_LEAST"}:
            if option_count == 0:
                errors.append(
                    "El grupo no tiene documentos activos configurados"
                )

        if rule == "AT_LEAST" and minimum > option_count:
            errors.append(
                "El mínimo exigido supera el número de "
                "documentos activos disponibles"
            )

        return {
            "grupo_id": int(group["id"]),
            "regla_cumplimiento": rule,
            "minimo_documentos": minimum,
            "documentos_activos": int(option_count),
            "valido": not errors,
            "errores": errors,
        }
