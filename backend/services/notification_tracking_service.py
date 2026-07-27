"""
Seguimiento operativo de notificaciones administrativas.

La tabla notification_tracking es una proyección operativa de la
trazabilidad activa del expediente. La fuente de verdad sigue siendo:

- expediente_justificantes;
- expedientes.numero_expediente_extranjeria;
- familia y notification_workflow_code del tipo de expediente.

Flujo EXTRANJERIA_STANDARD:

JUSTIFICANTE_PRESENTACION
    -> ESPERA_NUMERO_EXPEDIENTE

numero_expediente_extranjeria
    -> ESPERA_ADMISION_TRAMITE

ADMISION_TRAMITE / ADMISION_TRAMITE_TASA
    -> ESPERA_RESOLUCION

RESOLUCION_FAVORABLE / RESOLUCION_DENEGATORIA
    -> cerrado e inactivo.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

WORKFLOW_EXTRANJERIA = "EXTRANJERIA_STANDARD"

ESTADO_ESPERA_NUMERO = (
    "ESPERA_NUMERO_EXPEDIENTE"
)
ESTADO_ESPERA_ADMISION = (
    "ESPERA_ADMISION_TRAMITE"
)
ESTADO_ESPERA_RESOLUCION = (
    "ESPERA_RESOLUCION"
)
ESTADO_CERRADO_FAVORABLE = (
    "CERRADO_FAVORABLE"
)
ESTADO_CERRADO_DENEGATORIO = (
    "CERRADO_DENEGATORIO"
)
ESTADO_CANCELADO_SIN_PRESENTACION = (
    "CANCELADO_SIN_PRESENTACION"
)
ESTADO_NO_APLICABLE = "NO_APLICABLE"

ACTIVE_STATES = {
    ESTADO_ESPERA_NUMERO,
    ESTADO_ESPERA_ADMISION,
    ESTADO_ESPERA_RESOLUCION,
}

ADMISSION_EVENT_CODES = {
    "ADMISION_TRAMITE",
    "ADMISION_TRAMITE_TASA",
}

FAVORABLE_EVENT_CODES = {
    "RESOLUCION_FAVORABLE",
}

DENIAL_EVENT_CODES = {
    "RESOLUCION_DENEGATORIA",
    "RESOLUCION_DESFAVORABLE",
}

RESOLUTION_EVENT_CODES = (
    FAVORABLE_EVENT_CODES
    | DENIAL_EVENT_CODES
)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def _connection(conn=None):
    owns_connection = conn is None
    connection = conn or _connect()

    try:
        yield connection

        if owns_connection:
            connection.commit()

    except Exception:
        if owns_connection:
            connection.rollback()
        raise

    finally:
        if owns_connection:
            connection.close()


def _dict(row):
    return dict(row) if row else None


def _text(value):
    return str(value or "").strip().upper()


def ensure_notification_tracking_schema(conn=None):
    with _connection(conn) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                expediente_id INTEGER NOT NULL UNIQUE,
                cliente_id INTEGER NOT NULL,

                familia_codigo TEXT,
                notification_workflow_code TEXT NOT NULL,

                estado TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,

                numero_expediente_interno TEXT,
                numero_presentacion_registro TEXT,
                numero_expediente_extranjeria TEXT,
                numero_registro_regage TEXT,
                registro_csv_geiser TEXT,

                justificante_presentacion_id INTEGER,
                justificante_admision_id INTEGER,
                justificante_resolucion_id INTEGER,

                tipo_admision TEXT,
                resultado_resolucion TEXT,

                fecha_inicio_espera_numero TEXT,
                fecha_inicio_espera_admision TEXT,
                fecha_inicio_espera_resolucion TEXT,
                closed_at TEXT,

                origen_ultima_sincronizacion TEXT,
                usuario_ultima_sincronizacion TEXT,

                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (expediente_id)
                    REFERENCES expedientes(id),
                FOREIGN KEY (cliente_id)
                    REFERENCES clientes(id)
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                ux_notification_tracking_expediente
            ON notification_tracking(expediente_id)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_notification_tracking_activo_estado
            ON notification_tracking(activo, estado)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_notification_tracking_cliente
            ON notification_tracking(cliente_id)
            """
        )


def _derive_tracking_state(snapshot):
    """
    Función pura que decide el estado desde una fotografía del expediente.
    """
    snapshot = dict(snapshot or {})

    workflow_code = _text(
        snapshot.get("notification_workflow_code")
    )

    if workflow_code != WORKFLOW_EXTRANJERIA:
        return {
            "estado": ESTADO_NO_APLICABLE,
            "activo": 0,
            "resultado_resolucion": "",
            "reason": "WORKFLOW_NO_APLICABLE",
        }

    if not snapshot.get("presentation_exists"):
        return {
            "estado":
                ESTADO_CANCELADO_SIN_PRESENTACION,
            "activo": 0,
            "resultado_resolucion": "",
            "reason": "SIN_PRESENTACION_ACTIVA",
        }

    resolution_code = _text(
        snapshot.get("resolution_event_code")
    )

    if resolution_code in FAVORABLE_EVENT_CODES:
        return {
            "estado": ESTADO_CERRADO_FAVORABLE,
            "activo": 0,
            "resultado_resolucion": "FAVORABLE",
            "reason": "RESOLUCION_FAVORABLE",
        }

    if resolution_code in DENIAL_EVENT_CODES:
        return {
            "estado": ESTADO_CERRADO_DENEGATORIO,
            "activo": 0,
            "resultado_resolucion": "DENEGATORIA",
            "reason": "RESOLUCION_DENEGATORIA",
        }

    if snapshot.get("admission_exists"):
        return {
            "estado": ESTADO_ESPERA_RESOLUCION,
            "activo": 1,
            "resultado_resolucion": "",
            "reason": "ADMISION_ACTIVA",
        }

    official_number = str(
        snapshot.get(
            "numero_expediente_extranjeria"
        )
        or ""
    ).strip()

    if official_number:
        return {
            "estado": ESTADO_ESPERA_ADMISION,
            "activo": 1,
            "resultado_resolucion": "",
            "reason": "NUMERO_EXPEDIENTE_DISPONIBLE",
        }

    return {
        "estado": ESTADO_ESPERA_NUMERO,
        "activo": 1,
        "resultado_resolucion": "",
        "reason": "PRESENTADO_SIN_NUMERO",
    }


def _load_expedient_snapshot(conn, expediente_id):
    expediente = conn.execute(
        """
        SELECT
            e.id AS expediente_id,
            e.cliente_id,
            e.numero_expediente,
            e.numero_presentacion_registro,
            e.numero_expediente_mercurio,
            e.numero_expediente_extranjeria,
            e.numero_registro_regage,
            e.registro_csv_geiser,
            e.estado_presentacion,
            e.activo AS expediente_activo,

            t.codigo AS tipo_codigo,
            t.nombre AS tipo_nombre,

            f.codigo AS familia_codigo,
            f.nombre AS familia_nombre,
            f.notification_workflow_code

        FROM expedientes e

        LEFT JOIN config_tipos_expediente t
          ON t.id = e.tipo_expediente_id

        LEFT JOIN config_familias_expediente f
          ON f.id = t.familia_id

        WHERE e.id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not expediente:
        raise ValueError("Expediente no encontrado")

    documents = conn.execute(
        """
        SELECT
            id,
            tipo_justificante,
            numero_expediente_documento,
            metadata_documento_json,
            fecha_documento,
            fecha_presentacion,
            created_at
        FROM expediente_justificantes
        WHERE expediente_id = ?
          AND activo = 1
        ORDER BY created_at ASC, id ASC
        """,
        (int(expediente_id),),
    ).fetchall()

    presentation = None
    admission = None
    resolution = None
    document_official_number = ""

    for row in documents:
        item = dict(row)
        event_code = _text(
            item.get("tipo_justificante")
        )

        detected_number = str(
            item.get("numero_expediente_documento")
            or ""
        ).strip()

        if detected_number:
            document_official_number = detected_number

        if event_code == "JUSTIFICANTE_PRESENTACION":
            presentation = item

        if event_code in ADMISSION_EVENT_CODES:
            admission = item

        if event_code in RESOLUTION_EVENT_CODES:
            resolution = item

    official_number = str(
        expediente[
            "numero_expediente_extranjeria"
        ]
        or document_official_number
        or ""
    ).strip()

    snapshot = dict(expediente)

    snapshot.update(
        {
            "presentation_exists":
                bool(presentation),
            "presentation_id":
                (
                    int(presentation["id"])
                    if presentation
                    else None
                ),

            "admission_exists":
                bool(admission),
            "admission_id":
                (
                    int(admission["id"])
                    if admission
                    else None
                ),
            "admission_event_code":
                (
                    _text(
                        admission[
                            "tipo_justificante"
                        ]
                    )
                    if admission
                    else ""
                ),

            "resolution_exists":
                bool(resolution),
            "resolution_id":
                (
                    int(resolution["id"])
                    if resolution
                    else None
                ),
            "resolution_event_code":
                (
                    _text(
                        resolution[
                            "tipo_justificante"
                        ]
                    )
                    if resolution
                    else ""
                ),

            "numero_expediente_extranjeria":
                official_number,

            "active_document_count":
                len(documents),
        }
    )

    return snapshot


def _event_description(
    estado_anterior,
    estado_nuevo,
    source,
    decision,
):
    return (
        "Sincronización del seguimiento de "
        "notificaciones.\n"
        f"Origen: {source or 'ERP'}.\n"
        f"Motivo: {decision.get('reason') or '-'}.\n"
        f"Estado: {estado_anterior or 'SIN REGISTRO'} "
        f"→ {estado_nuevo or 'SIN ESTADO'}."
    )

def _register_tracking_event(
    conn,
    *,
    expediente_id,
    cliente_id,
    tracking_id,
    estado_anterior,
    estado_nuevo,
    source,
    usuario,
    decision,
):
    if estado_anterior == estado_nuevo:
        return None

    cursor = conn.execute(
        """
        INSERT INTO expediente_eventos (
            expediente_id,
            cliente_id,
            tipo_evento,
            titulo,
            descripcion,
            estado_anterior,
            estado_nuevo,
            entidad_relacionada,
            entidad_relacionada_id,
            usuario
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(expediente_id),
            int(cliente_id),
            "NOTIFICATION_TRACKING_UPDATED",
            "SEGUIMIENTO DE NOTIFICACIONES ACTUALIZADO",
            _event_description(
                estado_anterior,
                estado_nuevo,
                source,
                decision,
            ),
            estado_anterior or "",
            estado_nuevo or "",
            "notification_tracking",
            int(tracking_id),
            str(usuario or "ERP").strip(),
        ),
    )

    return cursor.lastrowid


def reconcile_expedient(
    expediente_id,
    *,
    source="ERP",
    usuario="ERP",
    conn=None,
):
    """
    Reconstruye completamente el seguimiento de un expediente.

    Es idempotente: ejecutar varias veces con la misma trazabilidad
    no crea registros duplicados ni cambia innecesariamente el estado.
    """
    expediente_id = int(expediente_id)

    with _connection(conn) as connection:
        ensure_notification_tracking_schema(
            connection
        )

        snapshot = _load_expedient_snapshot(
            connection,
            expediente_id,
        )

        decision = _derive_tracking_state(
            snapshot
        )

        existing = connection.execute(
            """
            SELECT *
            FROM notification_tracking
            WHERE expediente_id = ?
            """,
            (expediente_id,),
        ).fetchone()

        existing = _dict(existing)

        estado_anterior = (
            existing.get("estado")
            if existing
            else ""
        )

        workflow_applicable = (
            _text(
                snapshot.get(
                    "notification_workflow_code"
                )
            )
            == WORKFLOW_EXTRANJERIA
        )

        # Un expediente ajeno al workflow que nunca tuvo
        # seguimiento no necesita una fila residual.
        if not workflow_applicable and not existing:
            return {
                "ok": True,
                "changed": False,
                "created": False,
                "expediente_id": expediente_id,
                "estado_anterior": "",
                "estado_nuevo": ESTADO_NO_APLICABLE,
                "activo": 0,
                "reason": "WORKFLOW_NO_APLICABLE",
                "tracking_id": None,
            }

        # No se crea seguimiento para expedientes que nunca
        # tuvieron una presentación documental activa.
        #
        # Si ya existía una fila, sí se conserva y pasa a
        # CANCELADO_SIN_PRESENTACION para mantener el historial
        # cuando la presentación se elimina desde trazabilidad.
        if (
            workflow_applicable
            and not snapshot.get("presentation_exists")
            and not existing
        ):
            return {
                "ok": True,
                "changed": False,
                "created": False,
                "expediente_id": expediente_id,
                "cliente_id": int(
                    snapshot["cliente_id"]
                ),
                "estado_anterior": "",
                "estado_nuevo":
                    ESTADO_CANCELADO_SIN_PRESENTACION,
                "activo": 0,
                "resultado_resolucion": "",
                "reason": "SIN_PRESENTACION_PREVIA",
                "tracking_id": None,
                "event_id": None,
                "snapshot": snapshot,
            }

        fecha_inicio_numero_sql = (
            """
            CASE
                WHEN notification_tracking.estado
                     != 'ESPERA_NUMERO_EXPEDIENTE'
                  OR notification_tracking.fecha_inicio_espera_numero
                     IS NULL
                THEN CURRENT_TIMESTAMP
                ELSE notification_tracking.fecha_inicio_espera_numero
            END
            """
            if decision["estado"] == ESTADO_ESPERA_NUMERO
            else "notification_tracking.fecha_inicio_espera_numero"
        )

        fecha_inicio_admision_sql = (
            """
            CASE
                WHEN notification_tracking.estado
                     != 'ESPERA_ADMISION_TRAMITE'
                  OR notification_tracking.fecha_inicio_espera_admision
                     IS NULL
                THEN CURRENT_TIMESTAMP
                ELSE notification_tracking.fecha_inicio_espera_admision
            END
            """
            if decision["estado"] == ESTADO_ESPERA_ADMISION
            else "notification_tracking.fecha_inicio_espera_admision"
        )

        fecha_inicio_resolucion_sql = (
            """
            CASE
                WHEN notification_tracking.estado
                     != 'ESPERA_RESOLUCION'
                  OR notification_tracking.fecha_inicio_espera_resolucion
                     IS NULL
                THEN CURRENT_TIMESTAMP
                ELSE notification_tracking.fecha_inicio_espera_resolucion
            END
            """
            if decision["estado"] == ESTADO_ESPERA_RESOLUCION
            else "notification_tracking.fecha_inicio_espera_resolucion"
        )

        closed_at_sql = (
            "CURRENT_TIMESTAMP"
            if not int(decision["activo"])
            else "NULL"
        )

        connection.execute(
            f"""
            INSERT INTO notification_tracking (
                expediente_id,
                cliente_id,
                familia_codigo,
                notification_workflow_code,
                estado,
                activo,

                numero_expediente_interno,
                numero_presentacion_registro,
                numero_expediente_extranjeria,
                numero_registro_regage,
                registro_csv_geiser,

                justificante_presentacion_id,
                justificante_admision_id,
                justificante_resolucion_id,

                tipo_admision,
                resultado_resolucion,

                fecha_inicio_espera_numero,
                fecha_inicio_espera_admision,
                fecha_inicio_espera_resolucion,
                closed_at,

                origen_ultima_sincronizacion,
                usuario_ultima_sincronizacion
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                CASE
                    WHEN ? = 'ESPERA_NUMERO_EXPEDIENTE'
                    THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                CASE
                    WHEN ? = 'ESPERA_ADMISION_TRAMITE'
                    THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                CASE
                    WHEN ? = 'ESPERA_RESOLUCION'
                    THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                CASE
                    WHEN ? = 0
                    THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                ?, ?
            )

            ON CONFLICT(expediente_id) DO UPDATE SET
                cliente_id = excluded.cliente_id,
                familia_codigo = excluded.familia_codigo,
                notification_workflow_code =
                    excluded.notification_workflow_code,
                estado = excluded.estado,
                activo = excluded.activo,

                numero_expediente_interno =
                    excluded.numero_expediente_interno,
                numero_presentacion_registro =
                    excluded.numero_presentacion_registro,
                numero_expediente_extranjeria =
                    excluded.numero_expediente_extranjeria,
                numero_registro_regage =
                    excluded.numero_registro_regage,
                registro_csv_geiser =
                    excluded.registro_csv_geiser,

                justificante_presentacion_id =
                    excluded.justificante_presentacion_id,
                justificante_admision_id =
                    excluded.justificante_admision_id,
                justificante_resolucion_id =
                    excluded.justificante_resolucion_id,

                tipo_admision =
                    excluded.tipo_admision,
                resultado_resolucion =
                    excluded.resultado_resolucion,

                fecha_inicio_espera_numero =
                    {fecha_inicio_numero_sql},

                fecha_inicio_espera_admision =
                    {fecha_inicio_admision_sql},

                fecha_inicio_espera_resolucion =
                    {fecha_inicio_resolucion_sql},

                closed_at = {closed_at_sql},

                origen_ultima_sincronizacion =
                    excluded.origen_ultima_sincronizacion,
                usuario_ultima_sincronizacion =
                    excluded.usuario_ultima_sincronizacion,

                updated_at = CURRENT_TIMESTAMP
            """,
            (
                expediente_id,
                int(snapshot["cliente_id"]),
                snapshot.get("familia_codigo") or "",
                snapshot.get(
                    "notification_workflow_code"
                )
                or "",
                decision["estado"],
                int(decision["activo"]),

                snapshot.get("numero_expediente") or "",
                snapshot.get(
                    "numero_presentacion_registro"
                )
                or snapshot.get(
                    "numero_expediente_mercurio"
                )
                or "",
                snapshot.get(
                    "numero_expediente_extranjeria"
                )
                or "",
                snapshot.get(
                    "numero_registro_regage"
                )
                or "",
                snapshot.get("registro_csv_geiser")
                or "",

                snapshot.get("presentation_id"),
                snapshot.get("admission_id"),
                snapshot.get("resolution_id"),

                snapshot.get(
                    "admission_event_code"
                )
                or "",
                decision.get(
                    "resultado_resolucion"
                )
                or "",

                decision["estado"],
                decision["estado"],
                decision["estado"],
                int(decision["activo"]),

                str(source or "ERP").strip(),
                str(usuario or "ERP").strip(),
            ),
        )

        tracking = connection.execute(
            """
            SELECT *
            FROM notification_tracking
            WHERE expediente_id = ?
            """,
            (expediente_id,),
        ).fetchone()

        tracking = _dict(tracking)

        estado_nuevo = tracking["estado"]

        changed = (
            not existing
            or estado_anterior != estado_nuevo
            or int(existing.get("activo") or 0)
               != int(tracking.get("activo") or 0)
            or str(
                existing.get(
                    "numero_expediente_extranjeria"
                )
                or ""
            ).strip()
               != str(
                    tracking.get(
                        "numero_expediente_extranjeria"
                    )
                    or ""
                ).strip()
            or existing.get(
                "justificante_presentacion_id"
            )
               != tracking.get(
                    "justificante_presentacion_id"
                )
            or existing.get(
                "justificante_admision_id"
            )
               != tracking.get(
                    "justificante_admision_id"
                )
            or existing.get(
                "justificante_resolucion_id"
            )
               != tracking.get(
                    "justificante_resolucion_id"
                )
        )

        event_id = None

        if estado_anterior != estado_nuevo:
            event_id = _register_tracking_event(
                connection,
                expediente_id=expediente_id,
                cliente_id=snapshot["cliente_id"],
                tracking_id=tracking["id"],
                estado_anterior=estado_anterior,
                estado_nuevo=estado_nuevo,
                source=source,
                usuario=usuario,
                decision=decision,
            )

        return {
            "ok": True,
            "changed": bool(changed),
            "created": not bool(existing),
            "tracking_id": int(tracking["id"]),
            "event_id": event_id,
            "expediente_id": expediente_id,
            "cliente_id": int(
                snapshot["cliente_id"]
            ),
            "estado_anterior":
                estado_anterior or "",
            "estado_nuevo": estado_nuevo,
            "activo": int(tracking["activo"]),
            "resultado_resolucion":
                tracking.get(
                    "resultado_resolucion"
                )
                or "",
            "reason": decision.get("reason") or "",
            "snapshot": snapshot,
        }


def reconcile_all_applicable_expedients(
    *,
    source="BACKFILL",
    usuario="ERP",
):
    ensure_notification_tracking_schema()

    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT e.id
            FROM expedientes e

            LEFT JOIN config_tipos_expediente t
              ON t.id = e.tipo_expediente_id

            LEFT JOIN config_familias_expediente f
              ON f.id = t.familia_id

            WHERE
                f.notification_workflow_code = ?
                OR EXISTS (
                    SELECT 1
                    FROM notification_tracking nt
                    WHERE nt.expediente_id = e.id
                )

            ORDER BY e.id ASC
            """,
            (WORKFLOW_EXTRANJERIA,),
        ).fetchall()

    results = []

    for row in rows:
        results.append(
            reconcile_expedient(
                row["id"],
                source=source,
                usuario=usuario,
            )
        )

    return results


def list_active_tracking(estado=None):
    ensure_notification_tracking_schema()

    sql = """
        SELECT
            nt.*,

            c.nombre AS cliente_nombre,
            c.primer_apellido AS cliente_primer_apellido,
            c.segundo_apellido AS cliente_segundo_apellido,
            c.nie AS cliente_nie,

            t.nombre AS tipo_expediente_nombre

        FROM notification_tracking nt

        JOIN clientes c
          ON c.id = nt.cliente_id

        JOIN expedientes e
          ON e.id = nt.expediente_id

        LEFT JOIN config_tipos_expediente t
          ON t.id = e.tipo_expediente_id

        WHERE nt.activo = 1
    """

    params = []

    if estado:
        sql += " AND nt.estado = ?"
        params.append(_text(estado))

    sql += """
        ORDER BY
            CASE nt.estado
                WHEN 'ESPERA_NUMERO_EXPEDIENTE'
                    THEN 10
                WHEN 'ESPERA_ADMISION_TRAMITE'
                    THEN 20
                WHEN 'ESPERA_RESOLUCION'
                    THEN 30
                ELSE 99
            END,
            nt.updated_at ASC,
            nt.id ASC
    """

    with _connection() as conn:
        return [
            dict(row)
            for row in conn.execute(
                sql,
                params,
            ).fetchall()
        ]


def get_tracking_by_expedient(expediente_id):
    ensure_notification_tracking_schema()

    with _connection() as conn:
        return _dict(
            conn.execute(
                """
                SELECT *
                FROM notification_tracking
                WHERE expediente_id = ?
                """,
                (int(expediente_id),),
            ).fetchone()
        )
