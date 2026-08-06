import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


CLIENT_ADMINISTRATIVE_COLUMNS = {
    "numero_soporte_nie": "TEXT",
    "localizacion_actual": "TEXT",
    "pais_localizacion_actual": "TEXT",
    "fecha_entrada_espana": "TEXT",
    "fecha_entrada_espana_aproximada":
        "INTEGER NOT NULL DEFAULT 0",
    "situacion_administrativa_id": "INTEGER",
    "autorizacion_actual_id": "INTEGER",
    "fecha_caducidad_origen": "TEXT",
    "fecha_caducidad_expediente_id": "INTEGER",
    "fecha_caducidad_documento_id": "INTEGER",
    "fecha_caducidad_actualizada_at": "TEXT",
    "updated_at": "TEXT",
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


def _authorization_catalog_migration_path():
    return (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260806_seed_client_authorization_catalog.sql"
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

        catalog_migration_path = (
            _authorization_catalog_migration_path()
        )

        if not catalog_migration_path.exists():
            raise FileNotFoundError(
                f"No existe la migración: "
                f"{catalog_migration_path}"
            )

        conn.executescript(
            catalog_migration_path.read_text(
                encoding="utf-8"
            )
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


ADMINISTRATIVE_UI_EXCLUDED_CODES = {
    "EN_ORIGEN",
    "NO_HA_ENTRADO_EN_ESPANA",
}


def list_administrative_situations(
    active_only=True,
    for_client_form=True,
):
    """
    Devuelve el catálogo de situaciones administrativas.

    La localización física se gestiona mediante
    clientes.localizacion_actual, por lo que la interfaz
    no mezcla EN_ORIGEN o NO_HA_ENTRADO_EN_ESPANA con la
    situación jurídica actual.
    """
    ensure_client_administrative_schema()

    sql = """
        SELECT *
        FROM config_situaciones_administrativas
        WHERE 1 = 1
    """
    params = []

    if active_only:
        sql += " AND COALESCE(activo, 1) = 1"

    if for_client_form:
        placeholders = ", ".join(
            "?"
            for _ in ADMINISTRATIVE_UI_EXCLUDED_CODES
        )

        sql += (
            " AND codigo NOT IN ("
            + placeholders
            + ")"
        )

        params.extend(
            sorted(
                ADMINISTRATIVE_UI_EXCLUDED_CODES
            )
        )

    sql += """
        ORDER BY
            COALESCE(orden, 9999),
            nombre
    """

    with _connection() as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def list_authorization_types(
    active_only=True,
    current_catalog_only=True,
    family_code=None,
):
    """
    Devuelve los tipos de autorización disponibles.

    El catálogo puede estar vacío durante las primeras
    fases de desarrollo; en ese caso se devuelve [].
    """
    ensure_client_administrative_schema()

    sql = """
        SELECT *
        FROM config_tipos_autorizacion
        WHERE 1 = 1
    """
    params = []

    if active_only:
        sql += " AND COALESCE(activo, 1) = 1"

    if current_catalog_only:
        sql += """
            AND COALESCE(
                estado_catalogo,
                'VIGENTE'
            ) = 'VIGENTE'
        """

    if family_code:
        sql += " AND familia_codigo = ?"
        params.append(
            str(family_code).strip().upper()
        )

    sql += """
        ORDER BY
            COALESCE(orden, 9999),
            nombre
    """

    with _connection() as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def update_client_administrative_snapshot(
    client_id,
    data,
    conn=None,
):
    """
    Actualiza la fotografía administrativa del cliente.

    No crea historial de autorizaciones. Se utiliza para
    localización, entrada en España y número de soporte.
    """
    owns_connection = conn is None

    if owns_connection:
        ensure_client_administrative_schema()
        conn = _connect()

    data = dict(
        data
        or {}
    )

    try:
        client = conn.execute(
            """
            SELECT id
            FROM clientes
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (
                int(client_id),
            ),
        ).fetchone()

        if not client:
            raise ValueError(
                "No existe el cliente activo"
            )

        conn.execute(
            """
            UPDATE clientes
            SET
                numero_soporte_nie = ?,
                localizacion_actual = ?,
                pais_localizacion_actual = ?,
                fecha_entrada_espana = ?,
                fecha_entrada_espana_aproximada = ?,
                situacion_administrativa_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                (
                    str(
                        data.get(
                            "numero_soporte_nie"
                        )
                        or ""
                    ).strip()
                    or None
                ),
                (
                    str(
                        data.get(
                            "localizacion_actual"
                        )
                        or ""
                    ).strip().upper()
                    or None
                ),
                (
                    str(
                        data.get(
                            "pais_localizacion_actual"
                        )
                        or ""
                    ).strip()
                    or None
                ),
                (
                    data.get(
                        "fecha_entrada_espana"
                    )
                    or None
                ),
                (
                    1
                    if data.get(
                        "fecha_entrada_espana_aproximada"
                    )
                    else 0
                ),
                (
                    int(
                        data[
                            "situacion_administrativa_id"
                        ]
                    )
                    if data.get(
                        "situacion_administrativa_id"
                    )
                    else None
                ),
                int(client_id),
            ),
        )

        row = conn.execute(
            """
            SELECT *
            FROM clientes
            WHERE id = ?
            """,
            (
                int(client_id),
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


def set_current_authorization(
    client_id,
    authorization_data,
    usuario="ERP",
):
    """
    Registra una autorización como actual.

    La autorización anterior deja de ser actual, pero se
    conserva en el historial. Después sincroniza clientes:
    situación, autorización actual y fecha de caducidad.
    """
    ensure_client_administrative_schema()

    data = dict(
        authorization_data
        or {}
    )

    situation_id = data.get(
        "situacion_administrativa_id"
    )

    authorization_type_id = data.get(
        "tipo_autorizacion_id"
    )

    if not situation_id:
        raise ValueError(
            "Selecciona la situación administrativa"
        )

    with _connection() as conn:
        client = conn.execute(
            """
            SELECT id
            FROM clientes
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (
                int(client_id),
            ),
        ).fetchone()

        if not client:
            raise ValueError(
                "No existe el cliente activo"
            )

        situation = conn.execute(
            """
            SELECT id
            FROM config_situaciones_administrativas
            WHERE id = ?
              AND COALESCE(activo, 1) = 1
            """,
            (
                int(situation_id),
            ),
        ).fetchone()

        if not situation:
            raise ValueError(
                "La situación administrativa "
                "no es válida"
            )

        if authorization_type_id:
            authorization_type = conn.execute(
                """
                SELECT id
                FROM config_tipos_autorizacion
                WHERE id = ?
                  AND COALESCE(activo, 1) = 1
                """,
                (
                    int(authorization_type_id),
                ),
            ).fetchone()

            if not authorization_type:
                raise ValueError(
                    "El tipo de autorización "
                    "no es válido"
                )

        previous = conn.execute(
            """
            SELECT id
            FROM cliente_autorizaciones
            WHERE cliente_id = ?
              AND es_actual = 1
              AND activo = 1
            LIMIT 1
            """,
            (
                int(client_id),
            ),
        ).fetchone()

        if previous:
            conn.execute(
                """
                UPDATE cliente_autorizaciones
                SET
                    es_actual = 0,
                    motivo_fin = COALESCE(
                        ?,
                        motivo_fin
                    ),
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    (
                        data.get(
                            "motivo_fin_anterior"
                        )
                        or (
                            "Sustituida por una nueva "
                            "situación o autorización actual."
                        )
                    ),
                    int(previous["id"]),
                ),
            )

        cursor = conn.execute(
            """
            INSERT INTO cliente_autorizaciones (
                cliente_id,
                situacion_administrativa_id,
                tipo_autorizacion_id,
                estado_autorizacion,
                fecha_solicitud,
                fecha_presentacion,
                fecha_concesion,
                fecha_notificacion,
                fecha_vigencia_desde,
                fecha_vigencia_hasta,
                numero_expediente_administrativo,
                organismo_concedente,
                provincia,
                expediente_origen_id,
                documento_origen_id,
                motivo_inicio,
                es_actual,
                activo,
                observaciones
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, 1, 1, ?
            )
            """,
            (
                int(client_id),
                int(situation_id),
                (
                    int(authorization_type_id)
                    if authorization_type_id
                    else None
                ),
                (
                    str(
                        data.get(
                            "estado_autorizacion"
                        )
                        or "VIGENTE"
                    ).strip().upper()
                ),
                data.get("fecha_solicitud") or None,
                data.get("fecha_presentacion") or None,
                data.get("fecha_concesion") or None,
                data.get("fecha_notificacion") or None,
                data.get("fecha_vigencia_desde") or None,
                data.get("fecha_vigencia_hasta") or None,
                (
                    data.get(
                        "numero_expediente_administrativo"
                    )
                    or None
                ),
                (
                    data.get(
                        "organismo_concedente"
                    )
                    or None
                ),
                data.get("provincia") or None,
                (
                    int(
                        data["expediente_origen_id"]
                    )
                    if data.get(
                        "expediente_origen_id"
                    )
                    else None
                ),
                (
                    int(
                        data["documento_origen_id"]
                    )
                    if data.get(
                        "documento_origen_id"
                    )
                    else None
                ),
                data.get("motivo_inicio") or None,
                data.get("observaciones") or None,
            ),
        )

        authorization_id = int(
            cursor.lastrowid
        )

        conn.execute(
            """
            UPDATE clientes
            SET
                situacion_administrativa_id = ?,
                autorizacion_actual_id = ?,
                fecha_caducidad_residencia =
                    COALESCE(
                        ?,
                        fecha_caducidad_residencia
                    ),
                fecha_caducidad_origen =
                    CASE
                        WHEN ? IS NOT NULL
                        THEN 'AUTORIZACION_CLIENTE'
                        ELSE fecha_caducidad_origen
                    END,
                fecha_caducidad_expediente_id =
                    COALESCE(
                        ?,
                        fecha_caducidad_expediente_id
                    ),
                fecha_caducidad_actualizada_at =
                    CURRENT_TIMESTAMP,
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(situation_id),
                authorization_id,
                data.get(
                    "fecha_vigencia_hasta"
                ),
                data.get(
                    "fecha_vigencia_hasta"
                ),
                (
                    int(
                        data["expediente_origen_id"]
                    )
                    if data.get(
                        "expediente_origen_id"
                    )
                    else None
                ),
                int(client_id),
            ),
        )

        row = conn.execute(
            """
            SELECT
                ca.*,
                sa.codigo AS situacion_codigo,
                sa.nombre AS situacion_nombre,
                ta.codigo AS autorizacion_codigo,
                ta.nombre AS autorizacion_nombre
            FROM cliente_autorizaciones ca
            LEFT JOIN config_situaciones_administrativas sa
              ON sa.id =
                 ca.situacion_administrativa_id
            LEFT JOIN config_tipos_autorizacion ta
              ON ta.id =
                 ca.tipo_autorizacion_id
            WHERE ca.id = ?
            """,
            (
                authorization_id,
            ),
        ).fetchone()

    return dict(row)


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
