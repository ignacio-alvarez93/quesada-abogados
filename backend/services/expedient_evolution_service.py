import sqlite3
from contextlib import contextmanager
from datetime import date
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
    """
    Garantiza el esquema de evolución de forma idempotente.

    Cuando participa en una transacción externa y las tablas ya
    existen, no ejecuta executescript(), porque SQLite podría confirmar
    implícitamente la transacción activa.
    """
    owns_connection = conn is None
    if owns_connection:
        conn = _connect()

    required_tables = {
        "expediente_relaciones",
        "config_transiciones_autorizacion",
        "config_reglas_expediente_derivado",
        "expediente_derivacion_propuestas",
    }

    try:
        existing_tables = {
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        if required_tables.issubset(existing_tables):
            return

        if not owns_connection and conn.in_transaction:
            raise RuntimeError(
                "El esquema de evolución debe inicializarse "
                "antes de comenzar la transacción operativa"
            )

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


def list_expedient_relations(
    expediente_id,
    direction="BOTH",
):
    """
    Lista las relaciones activas de un expediente.

    direction:
    - OUTGOING: expedientes creados o vinculados desde el actual.
    - INCOMING: expedientes desde los que procede el actual.
    - BOTH: ambas direcciones.

    Mantiene los campos legacy de origen y destino y añade una
    proyección enriquecida del expediente relacionado.
    """
    ensure_expedient_evolution_schema()

    expediente_id = int(expediente_id)
    normalized_direction = (
        _normalize_code(direction)
        or "BOTH"
    )

    if normalized_direction not in {
        "OUTGOING",
        "INCOMING",
        "BOTH",
    }:
        raise ValueError(
            "Dirección de relación no permitida: "
            f"{normalized_direction}"
        )

    direction_conditions = {
        "OUTGOING": (
            "r.expediente_origen_id = ?"
        ),
        "INCOMING": (
            "r.expediente_destino_id = ?"
        ),
        "BOTH": (
            "("
            "r.expediente_origen_id = ? "
            "OR r.expediente_destino_id = ?"
            ")"
        ),
    }

    params = (
        [expediente_id, expediente_id]
        if normalized_direction == "BOTH"
        else [expediente_id]
    )

    with _connection() as conn:
        has_admin_states = _table_exists(
            conn,
            "config_estados_administrativos",
        )

        if has_admin_states:
            state_select = """
                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN ead.codigo
                    ELSE eao.codigo
                END AS estado_relacionado_codigo,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN ead.nombre
                    ELSE eao.nombre
                END AS estado_relacionado_nombre,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN ead.color
                    ELSE eao.color
                END AS estado_relacionado_color
            """

            state_joins = """
                LEFT JOIN config_estados_administrativos eao
                  ON eao.id = eo.estado_administrativo_id

                LEFT JOIN config_estados_administrativos ead
                  ON ead.id = ed.estado_administrativo_id
            """

            state_params = [
                expediente_id,
                expediente_id,
                expediente_id,
            ]

        else:
            state_select = """
                NULL AS estado_relacionado_codigo,
                NULL AS estado_relacionado_nombre,
                NULL AS estado_relacionado_color
            """

            state_joins = ""
            state_params = []

        sql = f"""
            SELECT
                r.*,

                eo.numero_expediente
                    AS expediente_origen_numero,
                ed.numero_expediente
                    AS expediente_destino_numero,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN 'OUTGOING'
                    ELSE 'INCOMING'
                END AS direccion,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN ed.id
                    ELSE eo.id
                END AS expediente_relacionado_id,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN ed.numero_expediente
                    ELSE eo.numero_expediente
                END AS expediente_relacionado_numero,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN ed.activo
                    ELSE eo.activo
                END AS expediente_relacionado_activo,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN td.codigo
                    ELSE tor.codigo
                END AS tipo_relacionado_codigo,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN td.nombre
                    ELSE tor.nombre
                END AS tipo_relacionado_nombre,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN fd.codigo
                    ELSE fo.codigo
                END AS familia_relacionada_codigo,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN fd.nombre
                    ELSE fo.nombre
                END AS familia_relacionada_nombre,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN sd.codigo
                    ELSE so.codigo
                END AS subtipo_relacionado_codigo,

                CASE
                    WHEN r.expediente_origen_id = ?
                    THEN sd.nombre
                    ELSE so.nombre
                END AS subtipo_relacionado_nombre,

                {state_select}

            FROM expediente_relaciones r

            JOIN expedientes eo
              ON eo.id = r.expediente_origen_id

            JOIN expedientes ed
              ON ed.id = r.expediente_destino_id

            LEFT JOIN config_tipos_expediente tor
              ON tor.id = eo.tipo_expediente_id

            LEFT JOIN config_tipos_expediente td
              ON td.id = ed.tipo_expediente_id

            LEFT JOIN config_familias_expediente fo
              ON fo.id = tor.familia_id

            LEFT JOIN config_familias_expediente fd
              ON fd.id = td.familia_id

            LEFT JOIN config_subtipos_expediente so
              ON so.id = eo.subtipo_expediente_id

            LEFT JOIN config_subtipos_expediente sd
              ON sd.id = ed.subtipo_expediente_id

            {state_joins}

            WHERE {direction_conditions[normalized_direction]}
              AND r.activo = 1

            ORDER BY
                r.created_at ASC,
                r.id ASC
        """

        query_params = (
            [expediente_id] * 10
            + state_params
            + params
        )

        rows = conn.execute(
            sql,
            query_params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def get_expedient_relation_chain(
    expediente_id,
):
    """
    Devuelve el componente completo de expedientes conectado
    al expediente indicado.

    La cadena se recorre en ambas direcciones:

    - relaciones entrantes: nivel negativo;
    - expediente consultado: nivel cero;
    - relaciones salientes: nivel positivo.

    La búsqueda evita ciclos y devuelve nodos y relaciones
    por separado para que el frontend pueda representarlos.
    """
    ensure_expedient_evolution_schema()

    root_id = int(expediente_id)

    with _connection() as conn:
        root = conn.execute(
            """
            SELECT
                id,
                cliente_id
            FROM expedientes
            WHERE id = ?
            """,
            (root_id,),
        ).fetchone()

        if not root:
            raise ValueError(
                "No existe el expediente raíz"
            )

        client_id = int(root["cliente_id"])

        relation_rows = conn.execute(
            """
            SELECT
                r.*
            FROM expediente_relaciones r
            JOIN expedientes eo
              ON eo.id = r.expediente_origen_id
            JOIN expedientes ed
              ON ed.id = r.expediente_destino_id
            WHERE r.activo = 1
              AND eo.cliente_id = ?
              AND ed.cliente_id = ?
            ORDER BY
                r.created_at ASC,
                r.id ASC
            """,
            (
                client_id,
                client_id,
            ),
        ).fetchall()

        outgoing = {}
        incoming = {}

        for row in relation_rows:
            relation = dict(row)

            origin_id = int(
                relation["expediente_origen_id"]
            )
            destination_id = int(
                relation["expediente_destino_id"]
            )

            outgoing.setdefault(
                origin_id,
                [],
            ).append(
                relation
            )

            incoming.setdefault(
                destination_id,
                [],
            ).append(
                relation
            )

        levels = {
            root_id: 0,
        }

        queue = [
            root_id,
        ]

        connected_relation_ids = set()

        while queue:
            current_id = queue.pop(0)
            current_level = levels[current_id]

            for relation in outgoing.get(
                current_id,
                [],
            ):
                connected_relation_ids.add(
                    int(relation["id"])
                )

                destination_id = int(
                    relation[
                        "expediente_destino_id"
                    ]
                )

                if destination_id not in levels:
                    levels[destination_id] = (
                        current_level + 1
                    )
                    queue.append(destination_id)

            for relation in incoming.get(
                current_id,
                [],
            ):
                connected_relation_ids.add(
                    int(relation["id"])
                )

                origin_id = int(
                    relation[
                        "expediente_origen_id"
                    ]
                )

                if origin_id not in levels:
                    levels[origin_id] = (
                        current_level - 1
                    )
                    queue.append(origin_id)

        connected_ids = sorted(
            levels.keys()
        )

        placeholders = ",".join(
            "?"
            for _ in connected_ids
        )

        has_admin_states = _table_exists(
            conn,
            "config_estados_administrativos",
        )

        if has_admin_states:
            state_select = """
                ea.codigo
                    AS estado_administrativo_codigo,
                ea.nombre
                    AS estado_administrativo_nombre,
                ea.color
                    AS estado_administrativo_color
            """

            state_join = """
                LEFT JOIN
                    config_estados_administrativos ea
                  ON ea.id =
                     e.estado_administrativo_id
            """

        else:
            state_select = """
                NULL AS estado_administrativo_codigo,
                NULL AS estado_administrativo_nombre,
                NULL AS estado_administrativo_color
            """

            state_join = ""

        node_rows = conn.execute(
            f"""
            SELECT
                e.id,
                e.cliente_id,
                e.numero_expediente,
                e.activo,
                e.created_at,

                t.codigo
                    AS tipo_expediente_codigo,
                t.nombre
                    AS tipo_expediente_nombre,

                f.codigo
                    AS familia_expediente_codigo,
                f.nombre
                    AS familia_expediente_nombre,

                s.codigo
                    AS subtipo_expediente_codigo,
                s.nombre
                    AS subtipo_expediente_nombre,

                {state_select}

            FROM expedientes e

            LEFT JOIN config_tipos_expediente t
              ON t.id = e.tipo_expediente_id

            LEFT JOIN config_familias_expediente f
              ON f.id = t.familia_id

            LEFT JOIN config_subtipos_expediente s
              ON s.id = e.subtipo_expediente_id

            {state_join}

            WHERE e.id IN ({placeholders})
            """,
            connected_ids,
        ).fetchall()

        nodes = []

        for row in node_rows:
            node = dict(row)
            node_id = int(node["id"])

            node["nivel"] = int(
                levels[node_id]
            )

            node["es_raiz"] = (
                node_id == root_id
            )

            nodes.append(node)

        nodes.sort(
            key=lambda item: (
                int(item["nivel"]),
                str(
                    item.get("numero_expediente")
                    or ""
                ),
                int(item["id"]),
            )
        )

        edges = [
            dict(row)
            for row in relation_rows
            if int(row["id"])
            in connected_relation_ids
        ]

        return {
            "expediente_raiz_id": root_id,
            "cliente_id": client_id,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "min_level": min(
                levels.values()
            ),
            "max_level": max(
                levels.values()
            ),
        }


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


def _insert_expedient_event_with_connection(
    conn,
    expediente_id,
    cliente_id,
    tipo_evento,
    titulo,
    descripcion,
    entidad_relacionada,
    entidad_relacionada_id,
    usuario,
):
    """
    Registra un evento usando la transacción activa.

    No abre conexión propia y no confirma la operación.
    """
    if not _table_exists(conn, "expediente_eventos"):
        raise RuntimeError(
            "No existe la tabla expediente_eventos"
        )

    cursor = conn.execute(
        """
        INSERT INTO expediente_eventos (
            expediente_id,
            cliente_id,
            tipo_evento,
            titulo,
            descripcion,
            entidad_relacionada,
            entidad_relacionada_id,
            usuario
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(expediente_id),
            int(cliente_id),
            _normalize_code(tipo_evento),
            _normalize_code(titulo),
            str(descripcion or "").strip(),
            _normalize_code(entidad_relacionada),
            (
                int(entidad_relacionada_id)
                if entidad_relacionada_id is not None
                else None
            ),
            str(usuario or "ERP").strip().upper(),
        ),
    )

    return int(cursor.lastrowid)


def _build_derived_expedient_data(
    proposal,
    origin,
    expediente_data=None,
):
    """
    Construye los datos del expediente derivado.

    Cliente, tipo y subtipo proceden siempre de la propuesta.
    """
    supplied = dict(expediente_data or {})

    origin_number = (
        str(origin["numero_expediente"] or "").strip()
        or f"#{origin['id']}"
    )

    default_observations = (
        "Expediente creado desde propuesta de derivación "
        f"del expediente {origin_number}."
    )

    data = {
        "cliente_id": int(proposal["cliente_id"]),
        "tipo_expediente_id": int(
            proposal["tipo_expediente_destino_id"]
        ),
        "subtipo_expediente_id": (
            int(proposal["subtipo_expediente_destino_id"])
            if proposal["subtipo_expediente_destino_id"]
            is not None
            else None
        ),
        "numero_expediente": "",
        "estado_documental_id": None,
        "estado_administrativo_id": None,
        "estado_presentacion": "NO PRESENTADO",
        "prioridad_id": origin["prioridad_id"],
        "responsable": origin["responsable"] or "",
        "fecha_apertura": date.today().isoformat(),
        "fecha_presentacion": None,
        "fecha_resolucion": None,
        "numero_registro": "",
        "organo_presentacion": "",
        "provincia": origin["provincia"] or "",
        "observaciones": default_observations,
        "observaciones_internas": "",
        "box_folder_path": "",
        "activo": 1,
    }

    protected_fields = {
        "cliente_id",
        "tipo_expediente_id",
        "subtipo_expediente_id",
    }

    for key, value in supplied.items():
        if key not in protected_fields:
            data[key] = value

    return data


def accept_derivation_proposal(
    proposal_id,
    expediente_data=None,
    usuario="ERP",
):
    """
    Acepta una propuesta y crea el expediente derivado de forma atómica.

    En una única transacción:

    - crea el expediente destino;
    - crea la relación origen-destino;
    - marca la propuesta como CREADA;
    - registra eventos en ambos expedientes.

    La operación es idempotente cuando la propuesta ya está creada.
    """
    from backend.services import expedient_service

    # La inicialización se realiza antes de comenzar la transacción
    # operativa para evitar commits implícitos de executescript().
    ensure_expedient_evolution_schema()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        proposal = conn.execute(
            """
            SELECT
                p.*,
                r.codigo AS regla_codigo,
                r.nombre AS regla_nombre,
                r.tipo_relacion,
                r.activo AS regla_activa
            FROM expediente_derivacion_propuestas p
            JOIN config_reglas_expediente_derivado r
              ON r.id = p.regla_derivacion_id
            WHERE p.id = ?
            """,
            (int(proposal_id),),
        ).fetchone()

        if not proposal:
            raise ValueError(
                "No existe la propuesta de derivación"
            )

        if (
            proposal["estado"] == "CREADA"
            and proposal["expediente_destino_id"]
        ):
            destination = conn.execute(
                """
                SELECT *
                FROM expedientes
                WHERE id = ?
                """,
                (
                    int(
                        proposal["expediente_destino_id"]
                    ),
                ),
            ).fetchone()

            conn.commit()

            return {
                "proposal": dict(proposal),
                "expediente_destino": (
                    dict(destination)
                    if destination
                    else None
                ),
                "created": False,
                "already_created": True,
            }

        if proposal["estado"] not in {
            "PENDIENTE",
            "ACEPTADA",
        }:
            raise ValueError(
                "La propuesta no puede aceptarse "
                f"desde el estado {proposal['estado']}"
            )

        if int(proposal["regla_activa"] or 0) != 1:
            raise ValueError(
                "La regla de derivación está inactiva"
            )

        origin = conn.execute(
            """
            SELECT
                id,
                cliente_id,
                numero_expediente,
                prioridad_id,
                responsable,
                provincia,
                activo
            FROM expedientes
            WHERE id = ?
            """,
            (
                int(proposal["expediente_origen_id"]),
            ),
        ).fetchone()

        if not origin:
            raise ValueError(
                "No existe el expediente de origen"
            )

        if int(origin["activo"] or 0) != 1:
            raise ValueError(
                "El expediente de origen está inactivo"
            )

        if (
            int(origin["cliente_id"])
            != int(proposal["cliente_id"])
        ):
            raise ValueError(
                "La propuesta no pertenece al cliente "
                "del expediente de origen"
            )

        derived_data = _build_derived_expedient_data(
            proposal,
            origin,
            expediente_data=expediente_data,
        )

        destination_id = (
            expedient_service
            ._create_expediente_with_connection(
                conn,
                derived_data,
            )
        )

        relation = create_expedient_relation(
            expediente_origen_id=int(
                proposal["expediente_origen_id"]
            ),
            expediente_destino_id=destination_id,
            tipo_relacion=proposal["tipo_relacion"],
            regla_origen_id=int(
                proposal["regla_derivacion_id"]
            ),
            creado_automaticamente=False,
            motivo=(
                proposal["motivo"]
                or proposal["regla_nombre"]
            ),
            created_by=usuario,
            conn=conn,
        )

        updated = conn.execute(
            """
            UPDATE expediente_derivacion_propuestas
            SET
                estado = 'CREADA',
                expediente_destino_id = ?,
                revisada_por = ?,
                revisada_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND estado IN ('PENDIENTE', 'ACEPTADA')
              AND expediente_destino_id IS NULL
            """,
            (
                int(destination_id),
                str(usuario or "ERP").strip().upper(),
                int(proposal_id),
            ),
        )

        if updated.rowcount != 1:
            raise RuntimeError(
                "No se pudo actualizar la propuesta "
                "de derivación"
            )

        destination = conn.execute(
            """
            SELECT id, numero_expediente
            FROM expedientes
            WHERE id = ?
            """,
            (int(destination_id),),
        ).fetchone()

        destination_number = (
            destination["numero_expediente"]
            if destination
            else f"#{destination_id}"
        )

        origin_number = (
            origin["numero_expediente"]
            or f"#{origin['id']}"
        )

        _insert_expedient_event_with_connection(
            conn=conn,
            expediente_id=int(origin["id"]),
            cliente_id=int(origin["cliente_id"]),
            tipo_evento=(
                "EXPEDIENTE_DERIVADO_CREADO"
            ),
            titulo="EXPEDIENTE DERIVADO CREADO",
            descripcion=(
                f"Se ha creado el expediente "
                f"{destination_number} mediante la regla "
                f"{proposal['regla_codigo']}."
            ),
            entidad_relacionada="EXPEDIENTE",
            entidad_relacionada_id=destination_id,
            usuario=usuario,
        )

        _insert_expedient_event_with_connection(
            conn=conn,
            expediente_id=destination_id,
            cliente_id=int(proposal["cliente_id"]),
            tipo_evento=(
                "EXPEDIENTE_CREADO_DESDE_DERIVACION"
            ),
            titulo=(
                "EXPEDIENTE CREADO DESDE DERIVACIÓN"
            ),
            descripcion=(
                f"Expediente creado desde "
                f"{origin_number} mediante la regla "
                f"{proposal['regla_codigo']}."
            ),
            entidad_relacionada="EXPEDIENTE",
            entidad_relacionada_id=int(origin["id"]),
            usuario=usuario,
        )

        result_proposal = conn.execute(
            """
            SELECT *
            FROM expediente_derivacion_propuestas
            WHERE id = ?
            """,
            (int(proposal_id),),
        ).fetchone()

        result_destination = conn.execute(
            """
            SELECT *
            FROM expedientes
            WHERE id = ?
            """,
            (int(destination_id),),
        ).fetchone()

        conn.commit()

        return {
            "proposal": dict(result_proposal),
            "expediente_destino": dict(
                result_destination
            ),
            "relation": relation,
            "created": True,
            "already_created": False,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()
def evaluate_derivation_rules_for_event(
    expediente_id,
    event_code,
    resultado=None,
    usuario="ERP",
    conn=None,
):
    """
    Evalúa las reglas activas aplicables a un evento de expediente.

    Las reglas pueden definir familia, tipo y subtipo de origen.
    Los campos NULL funcionan como comodines.

    La creación de propuestas es idempotente gracias a la restricción
    única expediente_origen_id + regla_derivacion_id.
    """
    normalized_event = _normalize_code(event_code)
    normalized_result = (
        _normalize_code(resultado)
        if resultado is not None
        else None
    )

    if not normalized_event:
        raise ValueError(
            "Se requiere un código de evento"
        )

    owns_connection = conn is None

    if owns_connection:
        ensure_expedient_evolution_schema()
        conn = _connect()
    else:
        ensure_expedient_evolution_schema(conn)

    try:
        expediente = conn.execute(
            """
            SELECT
                e.id,
                e.cliente_id,
                e.tipo_expediente_id,
                e.subtipo_expediente_id,
                e.activo,
                t.familia_id
            FROM expedientes e
            JOIN config_tipos_expediente t
              ON t.id = e.tipo_expediente_id
            WHERE e.id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

        if not expediente:
            raise ValueError(
                "No existe el expediente"
            )

        if int(expediente["activo"] or 0) != 1:
            raise ValueError(
                "El expediente está inactivo"
            )

        rules = conn.execute(
            """
            SELECT
                r.*
            FROM config_reglas_expediente_derivado r
            WHERE r.activo = 1
              AND UPPER(TRIM(r.evento_disparador)) = ?
              AND (
                    r.familia_origen_id IS NULL
                 OR r.familia_origen_id = ?
              )
              AND (
                    r.tipo_expediente_origen_id IS NULL
                 OR r.tipo_expediente_origen_id = ?
              )
              AND (
                    r.subtipo_expediente_origen_id IS NULL
                 OR r.subtipo_expediente_origen_id = ?
              )
            ORDER BY
                CASE
                    WHEN r.subtipo_expediente_origen_id
                         IS NOT NULL
                    THEN 4
                    WHEN r.tipo_expediente_origen_id
                         IS NOT NULL
                    THEN 3
                    WHEN r.familia_origen_id
                         IS NOT NULL
                    THEN 2
                    ELSE 1
                END DESC,
                r.orden ASC,
                r.id ASC
            """,
            (
                normalized_event,
                expediente["familia_id"],
                expediente["tipo_expediente_id"],
                expediente["subtipo_expediente_id"],
            ),
        ).fetchall()

        created = []
        skipped = []

        for rule in rules:
            required_result = (
                _normalize_code(
                    rule["resultado_requerido"]
                )
                if rule["resultado_requerido"]
                else None
            )

            if required_result:
                if not normalized_result:
                    skipped.append(
                        {
                            "regla_id": int(rule["id"]),
                            "regla_codigo": rule["codigo"],
                            "reason": (
                                "RESULTADO_NO_INFORMADO"
                            ),
                        }
                    )
                    continue

                if required_result != normalized_result:
                    skipped.append(
                        {
                            "regla_id": int(rule["id"]),
                            "regla_codigo": rule["codigo"],
                            "reason": (
                                "RESULTADO_NO_COINCIDE"
                            ),
                        }
                    )
                    continue

            existing = conn.execute(
                """
                SELECT *
                FROM expediente_derivacion_propuestas
                WHERE expediente_origen_id = ?
                  AND regla_derivacion_id = ?
                """,
                (
                    int(expediente_id),
                    int(rule["id"]),
                ),
            ).fetchone()

            proposal = create_derivation_proposal(
                expediente_origen_id=int(
                    expediente_id
                ),
                regla_derivacion_id=int(rule["id"]),
                detectada_por_evento=normalized_event,
                motivo=(
                    f"Regla {rule['codigo']} activada "
                    f"por el evento {normalized_event}."
                ),
                conn=conn,
            )

            created.append(
                {
                    "proposal": proposal,
                    "created": existing is None,
                    "already_existed": existing is not None,
                    "regla_codigo": rule["codigo"],
                }
            )

            if (
                existing is None
                and _table_exists(
                    conn,
                    "expediente_eventos",
                )
            ):
                _insert_expedient_event_with_connection(
                    conn=conn,
                    expediente_id=int(expediente_id),
                    cliente_id=int(
                        expediente["cliente_id"]
                    ),
                    tipo_evento=(
                        "PROPUESTA_DERIVACION_GENERADA"
                    ),
                    titulo=(
                        "PROPUESTA DE DERIVACIÓN GENERADA"
                    ),
                    descripcion=(
                        f"El evento {normalized_event} "
                        f"ha activado la regla "
                        f"{rule['codigo']}."
                    ),
                    entidad_relacionada=(
                        "EXPEDIENTE_DERIVACION_PROPUESTA"
                    ),
                    entidad_relacionada_id=int(
                        proposal["id"]
                    ),
                    usuario=usuario,
                )

        if owns_connection:
            conn.commit()

        return {
            "expediente_id": int(expediente_id),
            "event_code": normalized_event,
            "resultado": normalized_result,
            "rules_evaluated": len(rules),
            "proposals": created,
            "skipped": skipped,
        }

    except Exception:
        if owns_connection:
            conn.rollback()
        raise

    finally:
        if owns_connection:
            conn.close()
