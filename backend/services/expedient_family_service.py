import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


DEFAULT_EXPEDIENT_FAMILIES = (
    (
        "EXTRANJERIA",
        "EXTRANJERÍA",
        "Procedimientos administrativos de extranjería tramitados principalmente ante Oficinas de Extranjería.",
        "EXTRANJERIA_STANDARD",
        10,
    ),
    (
        "NACIONALIDAD",
        "NACIONALIDAD",
        "Procedimientos de adquisición, conservación, recuperación y opción de nacionalidad española.",
        "RESOLUCION_DIRECTA",
        20,
    ),
    (
        "VISADOS",
        "VISADOS",
        "Procedimientos de visado tramitados ante consulados y oficinas consulares.",
        "RESOLUCION_DIRECTA",
        30,
    ),
    (
        "UGE",
        "UNIDAD DE GRANDES EMPRESAS",
        "Procedimientos tramitados ante la Unidad de Grandes Empresas y Colectivos Estratégicos.",
        "RESOLUCION_DIRECTA",
        40,
    ),
    (
        "CANCELACION_ANTECEDENTES",
        "CANCELACIÓN DE ANTECEDENTES",
        "Procedimientos de cancelación de antecedentes penales o policiales.",
        "RESOLUCION_DIRECTA",
        50,
    ),
    (
        "ASILO",
        "ASILO Y PROTECCIÓN INTERNACIONAL",
        "Procedimientos de asilo, protección subsidiaria y protección internacional.",
        "RESOLUCION_DIRECTA",
        60,
    ),
    (
        "OTROS",
        "OTROS",
        "Familia residual para procedimientos todavía no clasificados.",
        "RESOLUCION_DIRECTA",
        999,
    ),
)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _connection():
    """
    Contexto SQLite que confirma o revierte la transacción
    y cierra siempre la conexión.

    El context manager nativo de sqlite3 controla la transacción,
    pero no cierra necesariamente la conexión, lo que bloquea
    archivos temporales en Windows.
    """
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


def _column_exists(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def ensure_expedient_family_schema(conn=None):
    """
    Garantiza de forma idempotente:

    - catálogo de familias;
    - familia_id en config_tipos_expediente;
    - índice por familia;
    - familias estructurales mínimas.

    Puede reutilizar una conexión existente para participar en la misma
    transacción de inicialización.
    """
    owns_connection = conn is None
    if owns_connection:
        conn = _connect()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config_familias_expediente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                notification_workflow_code TEXT NOT NULL
                    DEFAULT 'RESOLUCION_DIRECTA',
                orden INTEGER NOT NULL DEFAULT 0,
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        if not _column_exists(conn, "config_tipos_expediente", "familia_id"):
            conn.execute(
                """
                ALTER TABLE config_tipos_expediente
                ADD COLUMN familia_id INTEGER
                """
            )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_config_tipos_familia
            ON config_tipos_expediente(familia_id, activo, nombre)
            """
        )

        for (
            codigo,
            nombre,
            descripcion,
            workflow_code,
            orden,
        ) in DEFAULT_EXPEDIENT_FAMILIES:
            conn.execute(
                """
                INSERT INTO config_familias_expediente (
                    codigo,
                    nombre,
                    descripcion,
                    notification_workflow_code,
                    orden,
                    activo
                )
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(codigo) DO UPDATE SET
                    nombre = excluded.nombre,
                    descripcion = excluded.descripcion,
                    notification_workflow_code =
                        excluded.notification_workflow_code,
                    orden = excluded.orden,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    codigo,
                    nombre,
                    descripcion,
                    workflow_code,
                    orden,
                ),
            )

        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


def assign_existing_types_to_families(conn=None):
    """
    Migra únicamente tipos ya conocidos.

    Regla conservadora:
    - NACIONALIDAD va a NACIONALIDAD.
    - Los tipos actuales marcados explícitamente con workflow EXTRANJERIA
      van a EXTRANJERIA.
    - No asigna automáticamente a EXTRANJERIA cualquier tipo futuro.
    - Los tipos no reconocidos quedan en OTROS.
    """
    owns_connection = conn is None
    if owns_connection:
        conn = _connect()

    try:
        ensure_expedient_family_schema(conn)

        family_ids = {
            row["codigo"]: int(row["id"])
            for row in conn.execute(
                """
                SELECT id, codigo
                FROM config_familias_expediente
                """
            ).fetchall()
        }

        conn.execute(
            """
            UPDATE config_tipos_expediente
            SET familia_id = ?
            WHERE UPPER(TRIM(COALESCE(workflow_code, ''))) = 'NACIONALIDAD'
              AND familia_id IS NULL
            """,
            (family_ids["NACIONALIDAD"],),
        )

        conn.execute(
            """
            UPDATE config_tipos_expediente
            SET familia_id = ?
            WHERE UPPER(TRIM(COALESCE(workflow_code, ''))) = 'EXTRANJERIA'
              AND familia_id IS NULL
            """,
            (family_ids["EXTRANJERIA"],),
        )

        conn.execute(
            """
            UPDATE config_tipos_expediente
            SET familia_id = ?
            WHERE familia_id IS NULL
            """,
            (family_ids["OTROS"],),
        )

        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


def initialize_expedient_families():
    with _connection() as conn:
        ensure_expedient_family_schema(conn)
        assign_existing_types_to_families(conn)
        conn.commit()


def get_expedient_families(active_only=True):
    sql = """
        SELECT *
        FROM config_familias_expediente
    """
    params = []

    if active_only:
        sql += " WHERE activo = ?"
        params.append(1)

    sql += " ORDER BY orden ASC, nombre ASC"

    with _connection() as conn:
        return [
            _dict(row)
            for row in conn.execute(sql, params).fetchall()
        ]


def get_expedient_family(family_id):
    with _connection() as conn:
        return _dict(
            conn.execute(
                """
                SELECT *
                FROM config_familias_expediente
                WHERE id = ?
                """,
                (int(family_id),),
            ).fetchone()
        )


def get_family_for_expedient_type(tipo_expediente_id):
    with _connection() as conn:
        return _dict(
            conn.execute(
                """
                SELECT f.*
                FROM config_tipos_expediente t
                JOIN config_familias_expediente f
                  ON f.id = t.familia_id
                WHERE t.id = ?
                """,
                (int(tipo_expediente_id),),
            ).fetchone()
        )
