import sqlite3
from pathlib import Path
from datetime import datetime

from backend.services import expedient_evolution_service
from backend.services import expedient_service


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


VALID_CREATION_ORIGINS = {
    "APERTURA_MANUAL",
    "DERIVACION_INTERNA",
    "CONTINUIDAD_MANUAL",
    "CONTINUIDAD_CON_HITO_EXTERNO",
    "MIGRACION_LEGACY",
    "IMPORTACION",
}


VALID_RELATION_ORIGINS = {
    "DERIVACION_AUTOMATICA",
    "VINCULACION_MANUAL",
    "MIGRACION_LEGACY",
    "IMPORTACION",
}


VALID_CONTINUITY_MODES = {
    "INDEPENDENT",
    "DIRECT_RELATION",
    "EXTERNAL_MILESTONE",
}


VALID_MILESTONE_STATES = {
    "REGISTRADO",
    "EN_TRAMITE",
    "FINALIZADO",
    "CANCELADO",
}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _normalize_code(value):
    return str(value or "").strip().upper()


def _raw_text(value):
    return str(value or "").strip()


def _migration_path():
    return (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "20260805_create_flexible_trajectory_schema.sql"
    )


def _table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (str(table_name),),
    ).fetchone()

    return row is not None


def ensure_flexible_trajectory_schema(conn=None):
    """
    Garantiza el esquema complementario de trayectoria flexible.

    Si participa en una transacción externa, las tablas deben haber
    sido inicializadas antes de comenzar dicha transacción.
    """
    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    required_tables = {
        "expediente_origenes_creacion",
        "expediente_relacion_origenes",
        "expediente_hitos_externos",
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
                "El esquema de trayectoria flexible debe "
                "inicializarse antes de comenzar la transacción"
            )

        migration = _migration_path()

        if not migration.exists():
            raise FileNotFoundError(
                f"No existe la migración: {migration}"
            )

        conn.executescript(
            migration.read_text(encoding="utf-8")
        )

        if owns_connection:
            conn.commit()

    finally:
        if owns_connection:
            conn.close()


def _get_active_expedient(conn, expediente_id):
    row = conn.execute(
        """
        SELECT
            id,
            cliente_id,
            numero_expediente,
            tipo_expediente_id,
            activo
        FROM expedientes
        WHERE id = ?
          AND COALESCE(activo, 1) = 1
        """,
        (int(expediente_id),),
    ).fetchone()

    return dict(row) if row else None


def _set_expedient_creation_origin_with_connection(
    conn,
    expediente_id,
    origen_creacion,
    descripcion=None,
    created_by="ERP",
):
    origin_code = _normalize_code(origen_creacion)

    if origin_code not in VALID_CREATION_ORIGINS:
        raise ValueError(
            "Origen de creación no permitido: "
            f"{origin_code}"
        )

    expediente = _get_active_expedient(
        conn,
        expediente_id,
    )

    if not expediente:
        raise ValueError(
            "No existe el expediente activo"
        )

    conn.execute(
        """
        INSERT INTO expediente_origenes_creacion (
            expediente_id,
            origen_creacion,
            descripcion,
            created_by
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT (expediente_id)
        DO UPDATE SET
            origen_creacion =
                excluded.origen_creacion,
            descripcion =
                excluded.descripcion,
            created_by =
                excluded.created_by,
            updated_at =
                CURRENT_TIMESTAMP
        """,
        (
            int(expediente_id),
            origin_code,
            _raw_text(descripcion) or None,
            _raw_text(created_by) or "ERP",
        ),
    )

    row = conn.execute(
        """
        SELECT *
        FROM expediente_origenes_creacion
        WHERE expediente_id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    return dict(row)


def set_expedient_creation_origin(
    expediente_id,
    origen_creacion,
    descripcion=None,
    created_by="ERP",
):
    ensure_flexible_trajectory_schema()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        result = (
            _set_expedient_creation_origin_with_connection(
                conn=conn,
                expediente_id=expediente_id,
                origen_creacion=origen_creacion,
                descripcion=descripcion,
                created_by=created_by,
            )
        )

        conn.commit()
        return result

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def get_expedient_creation_origin(
    expediente_id,
):
    ensure_flexible_trajectory_schema()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM expediente_origenes_creacion
            WHERE expediente_id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

    if row:
        return dict(row)

    return {
        "expediente_id": int(expediente_id),
        "origen_creacion": "APERTURA_MANUAL",
        "descripcion": (
            "Origen inferido por compatibilidad "
            "con expedientes históricos."
        ),
        "created_by": None,
        "inferred": True,
    }


def _set_relation_origin_with_connection(
    conn,
    relacion_id,
    origen_relacion,
    descripcion=None,
    created_by="ERP",
):
    relation_origin = _normalize_code(
        origen_relacion
    )

    if relation_origin not in VALID_RELATION_ORIGINS:
        raise ValueError(
            "Origen de relación no permitido: "
            f"{relation_origin}"
        )

    relation = conn.execute(
        """
        SELECT id
        FROM expediente_relaciones
        WHERE id = ?
          AND COALESCE(activo, 1) = 1
        """,
        (int(relacion_id),),
    ).fetchone()

    if not relation:
        raise ValueError(
            "No existe la relación activa"
        )

    conn.execute(
        """
        INSERT INTO expediente_relacion_origenes (
            relacion_id,
            origen_relacion,
            descripcion,
            created_by
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT (relacion_id)
        DO UPDATE SET
            origen_relacion =
                excluded.origen_relacion,
            descripcion =
                excluded.descripcion,
            created_by =
                excluded.created_by,
            updated_at =
                CURRENT_TIMESTAMP
        """,
        (
            int(relacion_id),
            relation_origin,
            _raw_text(descripcion) or None,
            _raw_text(created_by) or "ERP",
        ),
    )

    row = conn.execute(
        """
        SELECT *
        FROM expediente_relacion_origenes
        WHERE relacion_id = ?
        """,
        (int(relacion_id),),
    ).fetchone()

    return dict(row)


def _would_create_cycle(
    conn,
    expediente_origen_id,
    expediente_destino_id,
):
    """
    Comprueba si ya existe un camino desde el destino hasta el origen.

    En ese caso, añadir origen → destino cerraría un ciclo.
    """
    row = conn.execute(
        """
        WITH RECURSIVE descendants(id) AS (
            SELECT expediente_destino_id
            FROM expediente_relaciones
            WHERE expediente_origen_id = ?
              AND COALESCE(activo, 1) = 1

            UNION

            SELECT r.expediente_destino_id
            FROM expediente_relaciones r
            JOIN descendants d
              ON d.id = r.expediente_origen_id
            WHERE COALESCE(r.activo, 1) = 1
        )
        SELECT 1
        FROM descendants
        WHERE id = ?
        LIMIT 1
        """,
        (
            int(expediente_destino_id),
            int(expediente_origen_id),
        ),
    ).fetchone()

    return row is not None


def _create_manual_relation_with_connection(
    conn,
    expediente_origen_id,
    expediente_destino_id,
    tipo_relacion="ACTUACION_POSTERIOR",
    motivo=None,
    usuario="ERP",
):
    if _would_create_cycle(
        conn,
        expediente_origen_id,
        expediente_destino_id,
    ):
        raise ValueError(
            "La vinculación crearía un ciclo "
            "en la trayectoria"
        )

    relation = (
        expedient_evolution_service
        .create_expedient_relation(
            expediente_origen_id=(
                int(expediente_origen_id)
            ),
            expediente_destino_id=(
                int(expediente_destino_id)
            ),
            tipo_relacion=tipo_relacion,
            regla_origen_id=None,
            creado_automaticamente=False,
            motivo=motivo,
            created_by=usuario,
            conn=conn,
        )
    )

    relation_origin = (
        _set_relation_origin_with_connection(
            conn=conn,
            relacion_id=relation["id"],
            origen_relacion=(
                "VINCULACION_MANUAL"
            ),
            descripcion=motivo,
            created_by=usuario,
        )
    )

    return {
        "relation": relation,
        "relation_origin": relation_origin,
    }


def create_manual_expedient_relation(
    expediente_origen_id,
    expediente_destino_id,
    tipo_relacion="ACTUACION_POSTERIOR",
    motivo=None,
    usuario="ERP",
):
    ensure_flexible_trajectory_schema()
    expedient_evolution_service.ensure_expedient_evolution_schema()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        result = _create_manual_relation_with_connection(
            conn=conn,
            expediente_origen_id=(
                expediente_origen_id
            ),
            expediente_destino_id=(
                expediente_destino_id
            ),
            tipo_relacion=tipo_relacion,
            motivo=motivo,
            usuario=usuario,
        )

        origin = _get_active_expedient(
            conn,
            expediente_origen_id,
        )
        destination = _get_active_expedient(
            conn,
            expediente_destino_id,
        )

        expedient_evolution_service._insert_expedient_event_with_connection(
            conn=conn,
            expediente_id=int(origin["id"]),
            cliente_id=int(origin["cliente_id"]),
            tipo_evento=(
                "EXPEDIENTE_POSTERIOR_VINCULADO"
            ),
            titulo=(
                "EXPEDIENTE POSTERIOR VINCULADO"
            ),
            descripcion=(
                "Se vinculó manualmente el expediente "
                f"{destination['numero_expediente']}."
            ),
            entidad_relacionada="EXPEDIENTE",
            entidad_relacionada_id=int(
                destination["id"]
            ),
            usuario=usuario,
        )

        expedient_evolution_service._insert_expedient_event_with_connection(
            conn=conn,
            expediente_id=int(destination["id"]),
            cliente_id=int(destination["cliente_id"]),
            tipo_evento=(
                "EXPEDIENTE_VINCULADO_MANUALMENTE"
            ),
            titulo=(
                "EXPEDIENTE VINCULADO MANUALMENTE"
            ),
            descripcion=(
                "El expediente se vinculó manualmente "
                "como continuación de "
                f"{origin['numero_expediente']}."
            ),
            entidad_relacionada="EXPEDIENTE",
            entidad_relacionada_id=int(
                origin["id"]
            ),
            usuario=usuario,
        )

        conn.commit()
        return result

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def _validate_milestone_expedients(
    conn,
    cliente_id,
    expediente_anterior_id=None,
    expediente_posterior_id=None,
):
    linked = []

    for expediente_id in [
        expediente_anterior_id,
        expediente_posterior_id,
    ]:
        if expediente_id is None:
            continue

        expediente = _get_active_expedient(
            conn,
            expediente_id,
        )

        if not expediente:
            raise ValueError(
                "No existe uno de los expedientes "
                "vinculados al hito"
            )

        if int(expediente["cliente_id"]) != int(
            cliente_id
        ):
            raise ValueError(
                "El hito y los expedientes deben "
                "pertenecer al mismo cliente"
            )

        linked.append(expediente)

    if not linked:
        raise ValueError(
            "El hito debe vincularse al menos "
            "con un expediente"
        )

    return linked


def _create_external_milestone_with_connection(
    conn,
    cliente_id,
    milestone,
    expediente_anterior_id=None,
    expediente_posterior_id=None,
    usuario="ERP",
):
    milestone = dict(milestone or {})

    _validate_milestone_expedients(
        conn=conn,
        cliente_id=cliente_id,
        expediente_anterior_id=(
            expediente_anterior_id
        ),
        expediente_posterior_id=(
            expediente_posterior_id
        ),
    )

    code = _normalize_code(
        milestone.get("codigo")
    )

    name = _raw_text(
        milestone.get("nombre")
    )

    state = (
        _normalize_code(
            milestone.get("estado")
            or "REGISTRADO"
        )
    )

    if not code:
        raise ValueError(
            "El hito externo necesita un código"
        )

    if not name:
        raise ValueError(
            "El hito externo necesita un nombre"
        )

    if state not in VALID_MILESTONE_STATES:
        raise ValueError(
            "Estado de hito no permitido: "
            f"{state}"
        )

    try:
        cursor = conn.execute(
            """
            INSERT INTO expediente_hitos_externos (
                cliente_id,
                codigo,
                nombre,
                familia_referencia_codigo,
                tipo_referencia_codigo,
                subtipo_referencia_codigo,
                fecha_inicio,
                fecha_fin,
                estado,
                resultado,
                observaciones,
                documento_referencia,
                expediente_anterior_id,
                expediente_posterior_id,
                orden,
                created_by,
                activo
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, 1
            )
            """,
            (
                int(cliente_id),
                code,
                name,
                (
                    _normalize_code(
                        milestone.get(
                            "familia_referencia_codigo"
                        )
                    )
                    or None
                ),
                (
                    _normalize_code(
                        milestone.get(
                            "tipo_referencia_codigo"
                        )
                    )
                    or None
                ),
                (
                    _normalize_code(
                        milestone.get(
                            "subtipo_referencia_codigo"
                        )
                    )
                    or None
                ),
                (
                    _raw_text(
                        milestone.get("fecha_inicio")
                    )
                    or None
                ),
                (
                    _raw_text(
                        milestone.get("fecha_fin")
                    )
                    or None
                ),
                state,
                (
                    _normalize_code(
                        milestone.get("resultado")
                    )
                    or None
                ),
                (
                    _raw_text(
                        milestone.get(
                            "observaciones"
                        )
                    )
                    or None
                ),
                (
                    _raw_text(
                        milestone.get(
                            "documento_referencia"
                        )
                    )
                    or None
                ),
                (
                    int(expediente_anterior_id)
                    if expediente_anterior_id
                    is not None
                    else None
                ),
                (
                    int(expediente_posterior_id)
                    if expediente_posterior_id
                    is not None
                    else None
                ),
                int(
                    milestone.get("orden")
                    or 0
                ),
                _raw_text(usuario) or "ERP",
            ),
        )

    except sqlite3.IntegrityError as exc:
        if "uq_hito_externo_activo_trayectoria" in str(
            exc
        ) or "UNIQUE constraint failed" in str(exc):
            raise ValueError(
                "Ya existe este hito externo "
                "en la trayectoria"
            ) from exc
        raise

    row = conn.execute(
        """
        SELECT *
        FROM expediente_hitos_externos
        WHERE id = ?
        """,
        (int(cursor.lastrowid),),
    ).fetchone()

    return dict(row)


def create_external_milestone(
    cliente_id,
    milestone,
    expediente_anterior_id=None,
    expediente_posterior_id=None,
    usuario="ERP",
):
    ensure_flexible_trajectory_schema()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        result = (
            _create_external_milestone_with_connection(
                conn=conn,
                cliente_id=cliente_id,
                milestone=milestone,
                expediente_anterior_id=(
                    expediente_anterior_id
                ),
                expediente_posterior_id=(
                    expediente_posterior_id
                ),
                usuario=usuario,
            )
        )

        conn.commit()
        return result

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def list_external_milestones(
    cliente_id=None,
    expediente_id=None,
    active_only=True,
):
    ensure_flexible_trajectory_schema()

    sql = """
        SELECT
            h.*,
            ea.numero_expediente
                AS expediente_anterior_numero,
            ep.numero_expediente
                AS expediente_posterior_numero
        FROM expediente_hitos_externos h
        LEFT JOIN expedientes ea
          ON ea.id = h.expediente_anterior_id
        LEFT JOIN expedientes ep
          ON ep.id = h.expediente_posterior_id
        WHERE 1 = 1
    """

    params = []

    if active_only:
        sql += " AND h.activo = 1"

    if cliente_id is not None:
        sql += " AND h.cliente_id = ?"
        params.append(int(cliente_id))

    if expediente_id is not None:
        sql += """
            AND (
                h.expediente_anterior_id = ?
                OR h.expediente_posterior_id = ?
            )
        """
        params.extend(
            [
                int(expediente_id),
                int(expediente_id),
            ]
        )

    sql += """
        ORDER BY
            h.orden ASC,
            h.created_at ASC,
            h.id ASC
    """

    with _connect() as conn:
        rows = conn.execute(
            sql,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]



VALID_MILESTONE_RESULTS = {
    "CONCEDIDO",
    "DENEGADO",
    "COMPLETADO",
    "DESISTIDO",
    "ARCHIVADO",
    "CANCELADO",
    "SIN_RESULTADO",
}


def _get_external_milestone_with_connection(
    conn,
    milestone_id,
    *,
    active_only=False,
):
    sql = """
        SELECT
            h.*,
            ea.numero_expediente
                AS expediente_anterior_numero,
            ep.numero_expediente
                AS expediente_posterior_numero
        FROM expediente_hitos_externos h
        LEFT JOIN expedientes ea
          ON ea.id = h.expediente_anterior_id
        LEFT JOIN expedientes ep
          ON ep.id = h.expediente_posterior_id
        WHERE h.id = ?
    """

    params = [int(milestone_id)]

    if active_only:
        sql += " AND h.activo = 1"

    row = conn.execute(
        sql,
        params,
    ).fetchone()

    return dict(row) if row else None


def get_external_milestone(
    milestone_id,
    *,
    active_only=False,
):
    ensure_flexible_trajectory_schema()

    with _connect() as conn:
        return _get_external_milestone_with_connection(
            conn,
            milestone_id,
            active_only=active_only,
        )


def _normalize_milestone_result(value):
    result = _normalize_code(value)

    if not result:
        return None

    if result not in VALID_MILESTONE_RESULTS:
        raise ValueError(
            "Resultado de hito no permitido: "
            f"{result}"
        )

    return (
        None
        if result == "SIN_RESULTADO"
        else result
    )


def _validate_milestone_dates(
    fecha_inicio,
    fecha_fin,
):
    fecha_inicio = _raw_text(fecha_inicio)
    fecha_fin = _raw_text(fecha_fin)

    if (
        fecha_inicio
        and fecha_fin
        and fecha_fin < fecha_inicio
    ):
        raise ValueError(
            "La fecha final del hito no puede ser "
            "anterior a la fecha inicial"
        )

    return (
        fecha_inicio or None,
        fecha_fin or None,
    )


def _linked_milestone_expedient_ids(milestone):
    result = []

    for field in (
        "expediente_anterior_id",
        "expediente_posterior_id",
    ):
        value = milestone.get(field)

        if value is None:
            continue

        value = int(value)

        if value not in result:
            result.append(value)

    return result


def _insert_milestone_events_with_connection(
    conn,
    *,
    milestone,
    event_type,
    title,
    description,
    usuario,
):
    for expediente_id in (
        _linked_milestone_expedient_ids(
            milestone
        )
    ):
        expediente = _get_active_expedient(
            conn,
            expediente_id,
        )

        if not expediente:
            continue

        (
            expedient_evolution_service
            ._insert_expedient_event_with_connection(
                conn=conn,
                expediente_id=int(
                    expediente["id"]
                ),
                cliente_id=int(
                    expediente["cliente_id"]
                ),
                tipo_evento=event_type,
                titulo=title,
                descripcion=description,
                entidad_relacionada=(
                    "HITO_EXTERNO"
                ),
                entidad_relacionada_id=int(
                    milestone["id"]
                ),
                usuario=usuario,
            )
        )


def update_external_milestone(
    milestone_id,
    data,
    usuario="ERP",
):
    """
    Actualiza los datos descriptivos de un hito.

    No permite modificar:
    - cliente_id
    - expediente_anterior_id
    - expediente_posterior_id
    """

    ensure_flexible_trajectory_schema()
    expedient_evolution_service.ensure_expedient_evolution_schema()

    data = dict(data or {})

    forbidden_fields = {
        "cliente_id",
        "expediente_anterior_id",
        "expediente_posterior_id",
    }

    attempted_forbidden = sorted(
        field
        for field in forbidden_fields
        if field in data
    )

    if attempted_forbidden:
        raise ValueError(
            "No se pueden modificar desde esta operación "
            "los extremos de la trayectoria: "
            + ", ".join(attempted_forbidden)
        )

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        existing = (
            _get_external_milestone_with_connection(
                conn,
                milestone_id,
                active_only=True,
            )
        )

        if not existing:
            raise ValueError(
                "El hito externo no existe o está inactivo"
            )

        code = _normalize_code(
            data.get(
                "codigo",
                existing.get("codigo"),
            )
        )

        name = _raw_text(
            data.get(
                "nombre",
                existing.get("nombre"),
            )
        )

        state = _normalize_code(
            data.get(
                "estado",
                existing.get("estado"),
            )
        )

        if not code:
            raise ValueError(
                "El hito externo necesita un código"
            )

        if not name:
            raise ValueError(
                "El hito externo necesita un nombre"
            )

        if state not in VALID_MILESTONE_STATES:
            raise ValueError(
                "Estado de hito no permitido: "
                f"{state}"
            )

        result = _normalize_milestone_result(
            data.get(
                "resultado",
                existing.get("resultado"),
            )
        )

        (
            fecha_inicio,
            fecha_fin,
        ) = _validate_milestone_dates(
            data.get(
                "fecha_inicio",
                existing.get("fecha_inicio"),
            ),
            data.get(
                "fecha_fin",
                existing.get("fecha_fin"),
            ),
        )

        if state == "FINALIZADO" and not fecha_fin:
            raise ValueError(
                "Un hito finalizado necesita fecha final"
            )

        if state != "FINALIZADO" and result in {
            "CONCEDIDO",
            "DENEGADO",
            "COMPLETADO",
            "DESISTIDO",
            "ARCHIVADO",
        }:
            raise ValueError(
                "El resultado indicado requiere que "
                "el hito esté finalizado"
            )

        try:
            conn.execute(
                """
                UPDATE expediente_hitos_externos
                SET
                    codigo = ?,
                    nombre = ?,
                    familia_referencia_codigo = ?,
                    tipo_referencia_codigo = ?,
                    subtipo_referencia_codigo = ?,
                    fecha_inicio = ?,
                    fecha_fin = ?,
                    estado = ?,
                    resultado = ?,
                    observaciones = ?,
                    documento_referencia = ?,
                    orden = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND activo = 1
                """,
                (
                    code,
                    name,
                    (
                        _normalize_code(
                            data.get(
                                "familia_referencia_codigo",
                                existing.get(
                                    "familia_referencia_codigo"
                                ),
                            )
                        )
                        or None
                    ),
                    (
                        _normalize_code(
                            data.get(
                                "tipo_referencia_codigo",
                                existing.get(
                                    "tipo_referencia_codigo"
                                ),
                            )
                        )
                        or None
                    ),
                    (
                        _normalize_code(
                            data.get(
                                "subtipo_referencia_codigo",
                                existing.get(
                                    "subtipo_referencia_codigo"
                                ),
                            )
                        )
                        or None
                    ),
                    fecha_inicio,
                    fecha_fin,
                    state,
                    result,
                    (
                        _raw_text(
                            data.get(
                                "observaciones",
                                existing.get(
                                    "observaciones"
                                ),
                            )
                        )
                        or None
                    ),
                    (
                        _raw_text(
                            data.get(
                                "documento_referencia",
                                existing.get(
                                    "documento_referencia"
                                ),
                            )
                        )
                        or None
                    ),
                    int(
                        data.get(
                            "orden",
                            existing.get("orden")
                            or 0,
                        )
                        or 0
                    ),
                    int(milestone_id),
                ),
            )

        except sqlite3.IntegrityError as exc:
            if (
                "UNIQUE constraint failed"
                in str(exc)
            ):
                raise ValueError(
                    "Ya existe este hito externo "
                    "en la trayectoria"
                ) from exc
            raise

        updated = (
            _get_external_milestone_with_connection(
                conn,
                milestone_id,
                active_only=True,
            )
        )

        description = (
            "Se actualizó el trámite externo "
            f"{updated['nombre']} "
            f"({updated['codigo']})."
        )

        _insert_milestone_events_with_connection(
            conn,
            milestone=updated,
            event_type=(
                "HITO_EXTERNO_ACTUALIZADO"
            ),
            title=(
                "HITO EXTERNO ACTUALIZADO"
            ),
            description=description,
            usuario=usuario,
        )

        conn.commit()
        return updated

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def complete_external_milestone(
    milestone_id,
    resultado,
    fecha_fin=None,
    observaciones=None,
    usuario="ERP",
):
    ensure_flexible_trajectory_schema()
    expedient_evolution_service.ensure_expedient_evolution_schema()

    result = _normalize_milestone_result(
        resultado
    )

    if not result:
        raise ValueError(
            "Selecciona un resultado para finalizar "
            "el hito"
        )

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        existing = (
            _get_external_milestone_with_connection(
                conn,
                milestone_id,
                active_only=True,
            )
        )

        if not existing:
            raise ValueError(
                "El hito externo no existe o está inactivo"
            )

        final_date = (
            _raw_text(fecha_fin)
            or datetime.today().strftime(
                "%Y-%m-%d"
            )
        )

        (
            _fecha_inicio,
            final_date,
        ) = _validate_milestone_dates(
            existing.get("fecha_inicio"),
            final_date,
        )

        final_observations = (
            _raw_text(observaciones)
            if observaciones is not None
            else existing.get("observaciones")
        )

        conn.execute(
            """
            UPDATE expediente_hitos_externos
            SET
                estado = 'FINALIZADO',
                resultado = ?,
                fecha_fin = ?,
                observaciones = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND activo = 1
            """,
            (
                result,
                final_date,
                final_observations or None,
                int(milestone_id),
            ),
        )

        updated = (
            _get_external_milestone_with_connection(
                conn,
                milestone_id,
                active_only=True,
            )
        )

        description = (
            "Se finalizó el trámite externo "
            f"{updated['nombre']} con resultado "
            f"{updated['resultado']}."
        )

        _insert_milestone_events_with_connection(
            conn,
            milestone=updated,
            event_type=(
                "HITO_EXTERNO_FINALIZADO"
            ),
            title=(
                "HITO EXTERNO FINALIZADO"
            ),
            description=description,
            usuario=usuario,
        )

        conn.commit()
        return updated

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def deactivate_external_milestone(
    milestone_id,
    usuario="ERP",
    motivo=None,
):
    ensure_flexible_trajectory_schema()
    expedient_evolution_service.ensure_expedient_evolution_schema()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        existing = (
            _get_external_milestone_with_connection(
                conn,
                milestone_id,
                active_only=True,
            )
        )

        if not existing:
            raise ValueError(
                "El hito externo no existe o está inactivo"
            )

        conn.execute(
            """
            UPDATE expediente_hitos_externos
            SET
                activo = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND activo = 1
            """,
            (int(milestone_id),),
        )

        description = (
            "Se desactivó el trámite externo "
            f"{existing['nombre']}."
        )

        if _raw_text(motivo):
            description += (
                " Motivo: "
                + _raw_text(motivo)
            )

        _insert_milestone_events_with_connection(
            conn,
            milestone=existing,
            event_type=(
                "HITO_EXTERNO_DESACTIVADO"
            ),
            title=(
                "HITO EXTERNO DESACTIVADO"
            ),
            description=description,
            usuario=usuario,
        )

        conn.commit()

        result = dict(existing)
        result["activo"] = 0

        return result

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def create_expedient_with_continuity(
    expediente_data,
    continuity=None,
    usuario="ERP",
):
    """
    Crea un expediente y registra su contexto de trayectoria.

    Modos:
    - INDEPENDENT
    - DIRECT_RELATION
    - EXTERNAL_MILESTONE
    """
    continuity = dict(continuity or {})

    mode = _normalize_code(
        continuity.get("mode")
        or "INDEPENDENT"
    )

    if mode not in VALID_CONTINUITY_MODES:
        raise ValueError(
            "Modo de continuidad no permitido: "
            f"{mode}"
        )

    ensure_flexible_trajectory_schema()
    expedient_evolution_service.ensure_expedient_evolution_schema()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        new_expedient_id = (
            expedient_service
            ._create_expediente_with_connection(
                conn,
                dict(expediente_data or {}),
            )
        )

        new_expedient = _get_active_expedient(
            conn,
            new_expedient_id,
        )

        if not new_expedient:
            raise RuntimeError(
                "No se pudo recuperar el expediente creado"
            )

        previous_id = continuity.get(
            "previous_expedient_id"
        )

        relation_result = None
        milestone_result = None

        if mode == "INDEPENDENT":
            creation_origin = "APERTURA_MANUAL"

            origin_description = (
                continuity.get("description")
                or "Expediente abierto directamente."
            )

        elif mode == "DIRECT_RELATION":
            if not previous_id:
                raise ValueError(
                    "Selecciona el expediente anterior"
                )

            creation_origin = "CONTINUIDAD_MANUAL"

            origin_description = (
                continuity.get("description")
                or (
                    "Expediente creado como continuidad "
                    "manual de otro expediente."
                )
            )

            relation_result = (
                _create_manual_relation_with_connection(
                    conn=conn,
                    expediente_origen_id=int(
                        previous_id
                    ),
                    expediente_destino_id=int(
                        new_expedient_id
                    ),
                    tipo_relacion=(
                        continuity.get(
                            "relation_type"
                        )
                        or "ACTUACION_POSTERIOR"
                    ),
                    motivo=(
                        continuity.get("reason")
                        or origin_description
                    ),
                    usuario=usuario,
                )
            )

        else:
            creation_origin = (
                "CONTINUIDAD_CON_HITO_EXTERNO"
            )

            origin_description = (
                continuity.get("description")
                or (
                    "Expediente creado como continuidad "
                    "de un trámite externo."
                )
            )

            milestone_result = (
                _create_external_milestone_with_connection(
                    conn=conn,
                    cliente_id=int(
                        new_expedient["cliente_id"]
                    ),
                    milestone=(
                        continuity.get("milestone")
                        or {}
                    ),
                    expediente_anterior_id=(
                        int(previous_id)
                        if previous_id
                        else None
                    ),
                    expediente_posterior_id=int(
                        new_expedient_id
                    ),
                    usuario=usuario,
                )
            )

        creation_origin_result = (
            _set_expedient_creation_origin_with_connection(
                conn=conn,
                expediente_id=new_expedient_id,
                origen_creacion=creation_origin,
                descripcion=origin_description,
                created_by=usuario,
            )
        )

        expedient_evolution_service._insert_expedient_event_with_connection(
            conn=conn,
            expediente_id=int(new_expedient_id),
            cliente_id=int(
                new_expedient["cliente_id"]
            ),
            tipo_evento=(
                "EXPEDIENTE_CREADO_MANUALMENTE"
            ),
            titulo=(
                "EXPEDIENTE CREADO MANUALMENTE"
            ),
            descripcion=origin_description,
            entidad_relacionada="EXPEDIENTE",
            entidad_relacionada_id=int(
                new_expedient_id
            ),
            usuario=usuario,
        )

        if mode == "DIRECT_RELATION":
            previous = _get_active_expedient(
                conn,
                previous_id,
            )

            expedient_evolution_service._insert_expedient_event_with_connection(
                conn=conn,
                expediente_id=int(previous["id"]),
                cliente_id=int(previous["cliente_id"]),
                tipo_evento=(
                    "EXPEDIENTE_POSTERIOR_VINCULADO"
                ),
                titulo=(
                    "EXPEDIENTE POSTERIOR VINCULADO"
                ),
                descripcion=(
                    "Se creó y vinculó manualmente "
                    f"{new_expedient['numero_expediente']}."
                ),
                entidad_relacionada="EXPEDIENTE",
                entidad_relacionada_id=int(
                    new_expedient_id
                ),
                usuario=usuario,
            )

            expedient_evolution_service._insert_expedient_event_with_connection(
                conn=conn,
                expediente_id=int(new_expedient_id),
                cliente_id=int(
                    new_expedient["cliente_id"]
                ),
                tipo_evento=(
                    "EXPEDIENTE_VINCULADO_MANUALMENTE"
                ),
                titulo=(
                    "EXPEDIENTE VINCULADO MANUALMENTE"
                ),
                descripcion=(
                    "El expediente continúa manualmente "
                    f"a {previous['numero_expediente']}."
                ),
                entidad_relacionada="EXPEDIENTE",
                entidad_relacionada_id=int(
                    previous["id"]
                ),
                usuario=usuario,
            )

        elif mode == "EXTERNAL_MILESTONE":
            milestone_name = (
                milestone_result["nombre"]
            )

            expedient_evolution_service._insert_expedient_event_with_connection(
                conn=conn,
                expediente_id=int(new_expedient_id),
                cliente_id=int(
                    new_expedient["cliente_id"]
                ),
                tipo_evento=(
                    "CONTINUIDAD_CON_HITO_EXTERNO"
                ),
                titulo=(
                    "CONTINUIDAD CON HITO EXTERNO"
                ),
                descripcion=(
                    "El expediente continúa después "
                    f"del trámite externo: {milestone_name}."
                ),
                entidad_relacionada="HITO_EXTERNO",
                entidad_relacionada_id=int(
                    milestone_result["id"]
                ),
                usuario=usuario,
            )

            if previous_id:
                previous = _get_active_expedient(
                    conn,
                    previous_id,
                )

                expedient_evolution_service._insert_expedient_event_with_connection(
                    conn=conn,
                    expediente_id=int(previous["id"]),
                    cliente_id=int(
                        previous["cliente_id"]
                    ),
                    tipo_evento=(
                        "HITO_EXTERNO_POSTERIOR_REGISTRADO"
                    ),
                    titulo=(
                        "HITO EXTERNO POSTERIOR REGISTRADO"
                    ),
                    descripcion=(
                        "Se registró el trámite externo "
                        f"{milestone_name} antes de "
                        f"{new_expedient['numero_expediente']}."
                    ),
                    entidad_relacionada="HITO_EXTERNO",
                    entidad_relacionada_id=int(
                        milestone_result["id"]
                    ),
                    usuario=usuario,
                )

        result_expedient = conn.execute(
            """
            SELECT *
            FROM expedientes
            WHERE id = ?
            """,
            (int(new_expedient_id),),
        ).fetchone()

        conn.commit()

        return {
            "expediente": dict(result_expedient),
            "creation_origin":
                creation_origin_result,
            "relation": relation_result,
            "milestone": milestone_result,
            "mode": mode,
            "created": True,
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()
