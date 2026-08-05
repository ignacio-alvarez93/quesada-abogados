import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


CLIENT_ADMINISTRATIVE_COLUMNS = {
    "numero_soporte_nie": "TEXT",
    "localizacion_actual": "TEXT",
    "pais_localizacion_actual": "TEXT",
    "fecha_entrada_espana": "TEXT",
    "fecha_entrada_espana_aproximada": "INTEGER NOT NULL DEFAULT 0",
    "situacion_administrativa_id": "INTEGER",
    "autorizacion_actual_id": "INTEGER",
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


def _table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn, table_name, column_name):
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    return any(row["name"] == column_name for row in rows)


def _migration_path():
    return (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260805_create_client_administrative_trajectory.sql"
    )


def ensure_client_administrative_schema(conn=None):
    """
    Garantiza de forma idempotente la infraestructura administrativa
    del cliente.

    Puede reutilizar una conexión existente para participar en una
    transacción superior.
    """
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

        if not _table_exists(conn, "clientes"):
            raise RuntimeError(
                "No existe la tabla clientes"
            )

        for column_name, column_definition in (
            CLIENT_ADMINISTRATIVE_COLUMNS.items()
        ):
            if not _column_exists(
                conn,
                "clientes",
                column_name,
            ):
                conn.execute(
                    f"""
                    ALTER TABLE clientes
                    ADD COLUMN {column_name}
                    {column_definition}
                    """
                )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_clientes_situacion_administrativa
            ON clientes(situacion_administrativa_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_clientes_autorizacion_actual
            ON clientes(autorizacion_actual_id)
            """
        )

        if owns_connection:
            conn.commit()
    finally:
        if owns_connection:
            conn.close()


def get_current_authorization(client_id):
    ensure_client_administrative_schema()

    with _connection() as conn:
        row = conn.execute(
            """
            SELECT
                ca.*,
                sa.codigo AS situacion_codigo,
                sa.nombre AS situacion_nombre,
                ta.codigo AS autorizacion_codigo,
                ta.nombre AS autorizacion_nombre,
                ta.familia_codigo AS autorizacion_familia
            FROM cliente_autorizaciones ca
            LEFT JOIN config_situaciones_administrativas sa
              ON sa.id = ca.situacion_administrativa_id
            LEFT JOIN config_tipos_autorizacion ta
              ON ta.id = ca.tipo_autorizacion_id
            WHERE ca.cliente_id = ?
              AND ca.es_actual = 1
              AND ca.activo = 1
            LIMIT 1
            """,
            (int(client_id),),
        ).fetchone()

    return dict(row) if row else None


def list_client_authorizations(client_id, active_only=True):
    ensure_client_administrative_schema()

    sql = """
        SELECT
            ca.*,
            sa.codigo AS situacion_codigo,
            sa.nombre AS situacion_nombre,
            ta.codigo AS autorizacion_codigo,
            ta.nombre AS autorizacion_nombre,
            ta.familia_codigo AS autorizacion_familia
        FROM cliente_autorizaciones ca
        LEFT JOIN config_situaciones_administrativas sa
          ON sa.id = ca.situacion_administrativa_id
        LEFT JOIN config_tipos_autorizacion ta
          ON ta.id = ca.tipo_autorizacion_id
        WHERE ca.cliente_id = ?
    """
    params = [int(client_id)]

    if active_only:
        sql += " AND ca.activo = 1"

    sql += """
        ORDER BY
            ca.es_actual DESC,
            COALESCE(
                ca.fecha_vigencia_desde,
                ca.fecha_concesion,
                ca.created_at
            ) DESC,
            ca.id DESC
    """

    with _connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(row) for row in rows]
