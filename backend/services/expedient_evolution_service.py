import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


VALID_RELATION_TYPES = {
    "PREDECESOR",
    "DERIVADO",
    "MODIFICACION",
    "RENOVACION",
    "PRORROGA",
    "RECUPERACION",
    "RESIDENCIA_INDEPENDIENTE",
    "REQUISITO_PREVIO",
    "ACTUACION_POSTERIOR",
    "SUSTITUYE",
    "CONTINUA",
}

VALID_PROPOSAL_STATES = {
    "PENDIENTE",
    "ACEPTADA",
    "DESCARTADA",
    "CREADA",
    "NO_APLICABLE",
    "ERROR",
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


def _migration_path():
    return (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260805_create_expedient_evolution_schema.sql"
    )


def ensure_expedient_evolution_schema(conn=None):
    owns_connection = conn is None
    if owns_connection:
        conn = _connect()

    try:
        migration_path = _migration_path()

        if not migration_path.exists():
            raise FileNotFoundError(
                f"No existe la migración: {migration_path}"
            )

        conn.executescript(
            migration_path.read_text(encoding="utf-8")
        )

        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


def _normalize_code(value):
    return str(value or "").strip().upper()


def create_expedient_relation(
    expediente_origen_id,
    expediente_destino_id,
    tipo_relacion,
    regla_origen_id=None,
    creado_automaticamente=False,
    motivo=None,
    created_by="ERP",
    conn=None,
):
    relation_type = _normalize_code(tipo_relacion)

    if relation_type not in VALID_RELATION_TYPES:
        raise ValueError(
            f"Tipo de relación no permitido: {relation_type}"
        )

    if int(expediente_origen_id) == int(expediente_destino_id):
        raise ValueError(
            "Un expediente no puede relacionarse consigo mismo"
        )

    owns_connection = conn is None
    if owns_connection:
        conn = _connect()

    try:
        ensure_expedient_evolution_schema(conn)

        origin = conn.execute(
            """
            SELECT id, cliente_id
            FROM expedientes
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (int(expediente_origen_id),),
        ).fetchone()

        destination = conn.execute(
            """
            SELECT id, cliente_id
            FROM expedientes
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (int(expediente_destino_id),),
        ).fetchone()

        if not origin:
            raise ValueError(
                "No existe el expediente de origen"
            )

        if not destination:
            raise ValueError(
                "No existe el expediente de destino"
            )

        if int(origin["cliente_id"]) != int(destination["cliente_id"]):
            raise ValueError(
                "Los expedientes relacionados deben pertenecer "
                "al mismo cliente principal"
            )

        conn.execute(
            """
            INSERT INTO expediente_relaciones (
                expediente_origen_id,
                expediente_destino_id,
                tipo_relacion,
                regla_origen_id,
                creado_automaticamente,
                motivo,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (
                expediente_origen_id,
                expediente_destino_id,
                tipo_relacion
            )
            DO UPDATE SET
                regla_origen_id = excluded.regla_origen_id,
                creado_automaticamente =
                    excluded.creado_automaticamente,
                motivo = excluded.motivo,
                created_by = excluded.created_by,
                estado = 'ACTIVA',
                activo = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(expediente_origen_id),
                int(expediente_destino_id),
                relation_type,
                (
                    int(regla_origen_id)
                    if regla_origen_id is not None
                    else None
                ),
                1 if creado_automaticamente else 0,
                str(motivo or "").strip() or None,
                str(created_by or "ERP").strip(),
            ),
        )

        row = conn.execute(
            """
            SELECT *
            FROM expediente_relaciones
            WHERE expediente_origen_id = ?
              AND expediente_destino_id = ?
              AND tipo_relacion = ?
            """,
            (
                int(expediente_origen_id),
                int(expediente_destino_id),
                relation_type,
            ),
        ).fetchone()

        if owns_connection:
            conn.commit()

        return dict(row)
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def list_expedient_relations(expediente_id):
    ensure_expedient_evolution_schema()

    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT
                r.*,
                eo.numero_expediente
                    AS expediente_origen_numero,
                ed.numero_expediente
                    AS expediente_destino_numero
            FROM expediente_relaciones r
            JOIN expedientes eo
              ON eo.id = r.expediente_origen_id
            JOIN expedientes ed
              ON ed.id = r.expediente_destino_id
            WHERE (
                    r.expediente_origen_id = ?
                 OR r.expediente_destino_id = ?
            )
              AND r.activo = 1
            ORDER BY r.created_at, r.id
            """,
            (
                int(expediente_id),
                int(expediente_id),
            ),
        ).fetchall()

    return [dict(row) for row in rows]


def create_derivation_proposal(
    expediente_origen_id,
    regla_derivacion_id,
    detectada_por_evento,
    motivo=None,
    datos_propuestos_json=None,
    conn=None,
):
    owns_connection = conn is None
    if owns_connection:
        conn = _connect()

    try:
        ensure_expedient_evolution_schema(conn)

        row = conn.execute(
            """
            SELECT
                e.id AS expediente_origen_id,
                e.cliente_id,
                r.id AS regla_derivacion_id,
                r.familia_destino_id,
                r.tipo_expediente_destino_id,
                r.subtipo_expediente_destino_id,
                r.activo
            FROM expedientes e
            JOIN config_reglas_expediente_derivado r
              ON r.id = ?
            WHERE e.id = ?
            """,
            (
                int(regla_derivacion_id),
                int(expediente_origen_id),
            ),
        ).fetchone()

        if not row:
            raise ValueError(
                "No existe el expediente o la regla de derivación"
            )

        if int(row["activo"] or 0) != 1:
            raise ValueError(
                "La regla de derivación está inactiva"
            )

        conn.execute(
            """
            INSERT INTO expediente_derivacion_propuestas (
                expediente_origen_id,
                regla_derivacion_id,
                cliente_id,
                familia_destino_id,
                tipo_expediente_destino_id,
                subtipo_expediente_destino_id,
                estado,
                motivo,
                datos_propuestos_json,
                detectada_por_evento,
                detectada_automaticamente
            )
            VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?, ?, 1)
            ON CONFLICT (
                expediente_origen_id,
                regla_derivacion_id
            )
            DO NOTHING
            """,
            (
                int(row["expediente_origen_id"]),
                int(row["regla_derivacion_id"]),
                int(row["cliente_id"]),
                int(row["familia_destino_id"]),
                int(row["tipo_expediente_destino_id"]),
                (
                    int(row["subtipo_expediente_destino_id"])
                    if row["subtipo_expediente_destino_id"]
                    is not None
                    else None
                ),
                str(motivo or "").strip() or None,
                datos_propuestos_json,
                _normalize_code(detectada_por_evento),
            ),
        )

        proposal = conn.execute(
            """
            SELECT *
            FROM expediente_derivacion_propuestas
            WHERE expediente_origen_id = ?
              AND regla_derivacion_id = ?
            """,
            (
                int(expediente_origen_id),
                int(regla_derivacion_id),
            ),
        ).fetchone()

        if owns_connection:
            conn.commit()

        return dict(proposal)
    except Exception:
        if owns_connection:
            conn.rollback()
        raise
    finally:
        if owns_connection:
            conn.close()


def list_derivation_proposals(
    expediente_origen_id=None,
    cliente_id=None,
    estado=None,
):
    ensure_expedient_evolution_schema()

    sql = """
        SELECT
            p.*,
            e.numero_expediente
                AS expediente_origen_numero,
            r.codigo AS regla_codigo,
            r.nombre AS regla_nombre,
            f.codigo AS familia_destino_codigo,
            f.nombre AS familia_destino_nombre,
            t.codigo AS tipo_destino_codigo,
            t.nombre AS tipo_destino_nombre,
            s.codigo AS subtipo_destino_codigo,
            s.nombre AS subtipo_destino_nombre
        FROM expediente_derivacion_propuestas p
        JOIN expedientes e
          ON e.id = p.expediente_origen_id
        JOIN config_reglas_expediente_derivado r
          ON r.id = p.regla_derivacion_id
        JOIN config_familias_expediente f
          ON f.id = p.familia_destino_id
        JOIN config_tipos_expediente t
          ON t.id = p.tipo_expediente_destino_id
        LEFT JOIN config_subtipos_expediente s
          ON s.id = p.subtipo_expediente_destino_id
        WHERE 1 = 1
    """
    params = []

    if expediente_origen_id is not None:
        sql += " AND p.expediente_origen_id = ?"
        params.append(int(expediente_origen_id))

    if cliente_id is not None:
        sql += " AND p.cliente_id = ?"
        params.append(int(cliente_id))

    if estado:
        normalized_state = _normalize_code(estado)
        if normalized_state not in VALID_PROPOSAL_STATES:
            raise ValueError(
                f"Estado de propuesta no permitido: {normalized_state}"
            )
        sql += " AND p.estado = ?"
        params.append(normalized_state)

    sql += " ORDER BY p.created_at DESC, p.id DESC"

    with _connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]
