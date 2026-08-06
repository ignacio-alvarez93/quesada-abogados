import sqlite3
from pathlib import Path

from backend.services import (
    client_administrative_status_service,
)


BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "database" / "quesada.db"

MIGRATION_PATH = (
    BASE_DIR
    / "database"
    / "migrations"
    / "20260806_seed_reagrupacion_authorization_transitions.sql"
)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_authorization_transition_seed(conn=None):
    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    try:
        conn.executescript(
            MIGRATION_PATH.read_text(
                encoding="utf-8"
            )
        )

        if owns_connection:
            conn.commit()

    except Exception:
        if owns_connection:
            conn.rollback()
        raise

    finally:
        if owns_connection:
            conn.close()


def _normalize(value):
    return str(value or "").strip().upper()


def resolve_transition_for_expedient(
    expediente_id,
    event_code,
    result_code=None,
    conn=None,
):
    normalized_event = _normalize(event_code)
    normalized_result = _normalize(result_code)

    if normalized_event != "RESOLUCION_FAVORABLE":
        return None

    if normalized_result and normalized_result != "CONCEDIDO":
        return None

    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    try:
        ensure_authorization_transition_seed(
            conn=conn
        )

        row = conn.execute(
            """
            SELECT
                e.id AS expediente_id,
                e.cliente_id,
                e.numero_expediente,
                e.fecha_presentacion,
                e.fecha_resolucion,
                e.provincia,

                t.familia_id,
                e.tipo_expediente_id,
                e.subtipo_expediente_id,

                tr.id AS transicion_id,
                tr.codigo AS transicion_codigo,
                tr.tipo_transicion,
                tr.autorizacion_origen_id,
                tr.autorizacion_resultado_id,

                a.codigo AS autorizacion_codigo,
                a.nombre AS autorizacion_nombre,
                a.categoria AS autorizacion_categoria
            FROM expedientes e

            JOIN config_tipos_expediente t
              ON t.id = e.tipo_expediente_id

            JOIN config_transiciones_autorizacion tr
              ON tr.activo = 1
             AND tr.requiere_resolucion_favorable = 1
             AND (
                    tr.familia_destino_id IS NULL
                 OR tr.familia_destino_id = t.familia_id
             )
             AND (
                    tr.tipo_expediente_destino_id IS NULL
                 OR tr.tipo_expediente_destino_id =
                    e.tipo_expediente_id
             )
             AND (
                    tr.subtipo_expediente_destino_id IS NULL
                 OR tr.subtipo_expediente_destino_id =
                    e.subtipo_expediente_id
             )

            JOIN config_tipos_autorizacion a
              ON a.id = tr.autorizacion_resultado_id
             AND a.activo = 1

            WHERE e.id = ?
              AND COALESCE(e.activo, 1) = 1

            ORDER BY
                CASE
                    WHEN tr.subtipo_expediente_destino_id
                         IS NOT NULL
                    THEN 4
                    WHEN tr.tipo_expediente_destino_id
                         IS NOT NULL
                    THEN 3
                    WHEN tr.familia_destino_id
                         IS NOT NULL
                    THEN 2
                    ELSE 1
                END DESC,
                tr.orden ASC,
                tr.id ASC

            LIMIT 1
            """,
            (
                int(expediente_id),
            ),
        ).fetchone()

        return dict(row) if row else None

    finally:
        if owns_connection:
            conn.close()


def _situation_code_for_authorization(
    authorization,
):
    category = _normalize(
        authorization.get(
            "autorizacion_categoria"
        )
    )

    mapping = {
        "RESIDENCIA_TEMPORAL":
            "RESIDENCIA_TEMPORAL",
        "RESIDENCIA_TEMPORAL_TRABAJO":
            "RESIDENCIA_TEMPORAL",
        "ARRAIGO":
            "RESIDENCIA_TEMPORAL",
        "OTRAS_CIRCUNSTANCIAS_EXCEPCIONALES":
            "RESIDENCIA_TEMPORAL",
        "RESIDENCIA_LARGA_DURACION":
            "RESIDENCIA_LARGA_DURACION",
        "ESTANCIA":
            "ESTANCIA_LARGA_DURACION",
    }

    return mapping.get(
        category,
        "DESCONOCIDA",
    )


def apply_favorable_resolution_to_client(
    expediente_id,
    documento_id,
    resolution_data=None,
    usuario="ERP",
    conn=None,
):
    resolution_data = dict(
        resolution_data or {}
    )

    owns_connection = conn is None

    if owns_connection:
        conn = _connect()
        conn.execute("BEGIN IMMEDIATE")

    try:
        transition = (
            resolve_transition_for_expedient(
                expediente_id=expediente_id,
                event_code=(
                    "RESOLUCION_FAVORABLE"
                ),
                result_code="CONCEDIDO",
                conn=conn,
            )
        )

        if not transition:
            if owns_connection:
                conn.commit()

            return {
                "applied": False,
                "reason":
                    "SIN_TRANSICION_CONFIGURADA",
            }

        existing_row = conn.execute(
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
              ON sa.id =
                 ca.situacion_administrativa_id
            LEFT JOIN config_tipos_autorizacion ta
              ON ta.id =
                 ca.tipo_autorizacion_id
            WHERE ca.cliente_id = ?
              AND ca.expediente_origen_id = ?
              AND ca.documento_origen_id = ?
              AND ca.tipo_autorizacion_id = ?
              AND ca.activo = 1
            LIMIT 1
            """,
            (
                int(transition["cliente_id"]),
                int(expediente_id),
                int(documento_id),
                int(
                    transition[
                        "autorizacion_resultado_id"
                    ]
                ),
            ),
        ).fetchone()

        if existing_row:
            if owns_connection:
                conn.commit()

            return {
                "applied": False,
                "already_applied": True,
                "reason":
                    "RESOLUCION_YA_APLICADA",
                "transition": transition,
                "authorization":
                    dict(existing_row),
            }

        situation_code = (
            _situation_code_for_authorization(
                transition
            )
        )

        situation = conn.execute(
            """
            SELECT id, codigo
            FROM config_situaciones_administrativas
            WHERE codigo = ?
              AND activo = 1
            LIMIT 1
            """,
            (
                situation_code,
            ),
        ).fetchone()

        if not situation:
            raise ValueError(
                "No existe la situación "
                f"administrativa {situation_code}"
            )

        current_row = conn.execute(
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
              ON sa.id =
                 ca.situacion_administrativa_id
            LEFT JOIN config_tipos_autorizacion ta
              ON ta.id =
                 ca.tipo_autorizacion_id
            WHERE ca.cliente_id = ?
              AND ca.es_actual = 1
              AND ca.activo = 1
            LIMIT 1
            """,
            (
                int(transition["cliente_id"]),
            ),
        ).fetchone()

        current = (
            dict(current_row)
            if current_row
            else None
        )

        transition_type = _normalize(
            transition["tipo_transicion"]
        )

        if (
            transition_type == "RENOVACION"
            and not current
        ):
            raise ValueError(
                "La renovación requiere una "
                "autorización actual previa"
            )

        if (
            transition_type == "RENOVACION"
            and int(
                current["tipo_autorizacion_id"]
            )
            != int(
                transition[
                    "autorizacion_resultado_id"
                ]
            )
        ):
            raise ValueError(
                "La autorización actual no coincide "
                "con la autorización que se renueva"
            )

        authorization_data = {
            "situacion_administrativa_id":
                int(situation["id"]),

            "tipo_autorizacion_id":
                int(
                    transition[
                        "autorizacion_resultado_id"
                    ]
                ),

            "estado_autorizacion":
                "VIGENTE",

            "fecha_presentacion":
                (
                    resolution_data.get(
                        "fecha_presentacion"
                    )
                    or transition.get(
                        "fecha_presentacion"
                    )
                ),

            "fecha_concesion":
                (
                    resolution_data.get(
                        "fecha_concesion"
                    )
                    or resolution_data.get(
                        "fecha_resolucion"
                    )
                    or transition.get(
                        "fecha_resolucion"
                    )
                ),

            "fecha_notificacion":
                resolution_data.get(
                    "fecha_notificacion"
                ),

            "fecha_vigencia_desde":
                (
                    resolution_data.get(
                        "fecha_vigencia_desde"
                    )
                    or resolution_data.get(
                        "fecha_efectos"
                    )
                ),

            "fecha_vigencia_hasta":
                (
                    resolution_data.get(
                        "fecha_vigencia_hasta"
                    )
                    or resolution_data.get(
                        "fecha_caducidad"
                    )
                ),

            "numero_expediente_administrativo":
                (
                    resolution_data.get(
                        "numero_expediente_administrativo"
                    )
                    or resolution_data.get(
                        "numero_expediente_extranjeria"
                    )
                    or transition.get(
                        "numero_expediente"
                    )
                ),

            "organismo_concedente":
                resolution_data.get(
                    "organismo_concedente"
                ),

            "provincia":
                (
                    resolution_data.get(
                        "provincia"
                    )
                    or transition.get(
                        "provincia"
                    )
                ),

            "expediente_origen_id":
                int(expediente_id),

            "documento_origen_id":
                int(documento_id),

            "motivo_inicio":
                (
                    "RESOLUCION_FAVORABLE_"
                    + transition_type
                ),

            "observaciones":
                (
                    "Autorización creada "
                    "automáticamente desde "
                    "la resolución favorable "
                    "del expediente."
                ),
        }

        created = (
            client_administrative_status_service
            .set_current_authorization(
                client_id=int(
                    transition["cliente_id"]
                ),
                authorization_data=(
                    authorization_data
                ),
                usuario=usuario,
                conn=conn,
            )
        )

        result = {
            "applied": True,
            "transition": transition,
            "authorization": created,
        }

        if owns_connection:
            conn.commit()

        return result

    except Exception:
        if owns_connection:
            conn.rollback()
        raise

    finally:
        if owns_connection:
            conn.close()
