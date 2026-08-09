import json
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime

from backend.services import justificante_presentacion_extraction_service as presentation_extractor

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _dict(row):
    return dict(row) if row else None


def _text(value):
    return (value or "").strip().upper()


def _raw(value):
    return (value or "").strip()


def _float(value):
    try:
        return float(str(value or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _int_or_none(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _column_exists(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def ensure_presentation_registry_runtime_schema(conn):
    columns = {
        "numero_presentacion_registro": "TEXT",
        "numero_expediente_extranjeria": "TEXT",
        "fecha_hora_presentacion": "TEXT",
        "fecha_hora_registro": "TEXT",
        "numero_registro_regage": "TEXT",
        "oficina_registro_nombre": "TEXT",
        "oficina_registro_codigo": "TEXT",
        "unidad_tramitacion_nombre": "TEXT",
        "unidad_tramitacion_codigo": "TEXT",
        "organismo_tramitacion": "TEXT",
        "registro_ambito_prefijo": "TEXT",
        "registro_csv_geiser": "TEXT",
        "justificante_presentacion_sha256": "TEXT",
        "justificante_extraction_status": "TEXT",
        "justificante_extraction_json": "TEXT",
        "justificante_extracted_at": "TEXT",
    }

    for column_name, column_type in columns.items():
        if not _column_exists(conn, "expedientes", column_name):
            conn.execute(
                f"ALTER TABLE expedientes ADD COLUMN {column_name} {column_type}"
            )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_expedientes_numero_presentacion
        ON expedientes(numero_presentacion_registro)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_expedientes_numero_extranjeria
        ON expedientes(numero_expediente_extranjeria)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_expedientes_regage
        ON expedientes(numero_registro_regage)
        """
    )


def initialize_traceability_schema():
    schema_path = Path(__file__).resolve().parents[2] / "database" / "expedient_traceability_schema.sql"
    with _connect() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        ensure_presentation_registry_runtime_schema(conn)
        conn.commit()


def get_expediente_basic(expediente_id):
    with closing(
        _connect()
    ) as conn:
        return _dict(
            conn.execute(
                """
                SELECT
                    e.*,
                    c.nombre,
                    c.primer_apellido,
                    c.segundo_apellido,
                    c.nie AS cliente_nie,
                    c.dni AS cliente_dni,
                    c.pasaporte AS cliente_pasaporte
                FROM expedientes e
                JOIN clientes c ON c.id = e.cliente_id
                WHERE e.id = ?
                """,
                (int(expediente_id),),
            ).fetchone()
        )


def registrar_evento(
    expediente_id,
    cliente_id,
    tipo_evento,
    titulo,
    descripcion="",
    estado_anterior="",
    estado_nuevo="",
    entidad_relacionada="",
    entidad_relacionada_id=None,
    usuario="",
    conn=None,
):
    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    try:
        cur = conn.execute(
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
                _text(tipo_evento),
                _text(titulo),
                _raw(descripcion),
                _text(estado_anterior),
                _text(estado_nuevo),
                _text(entidad_relacionada),
                entidad_relacionada_id,
                _text(usuario),
            ),
        )

        if owns_connection:
            conn.commit()

        return cur.lastrowid

    except Exception:
        if owns_connection:
            conn.rollback()
        raise

    finally:
        if owns_connection:
            conn.close()


def get_eventos_expediente(expediente_id):
    with _connect() as conn:
        return [
            _dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM expediente_eventos
                WHERE expediente_id = ?
                ORDER BY fecha_evento DESC, id DESC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]


ADMIN_DOCUMENT_METADATA_COLUMNS = {
    "fecha_documento": "TEXT",
    "csv_documento": "TEXT",
    "dir3_documento": "TEXT",
    "organo_documento": "TEXT",
    "nie_documento": "TEXT",
    "numero_expediente_documento": "TEXT",
    "metadata_documento_json": "TEXT",
}


def ensure_admin_document_metadata_schema(conn):
    for column_name, column_type in (
        ADMIN_DOCUMENT_METADATA_COLUMNS.items()
    ):
        if not _column_exists(
            conn,
            "expediente_justificantes",
            column_name,
        ):
            conn.execute(
                f"""
                ALTER TABLE expediente_justificantes
                ADD COLUMN {column_name} {column_type}
                """
            )


def create_justificante(
    data,
    conn=None,
):
    expediente_id = int(
        data.get("expediente_id")
    )

    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    try:
        ensure_admin_document_metadata_schema(
            conn
        )

        expediente = conn.execute(
            """
            SELECT
                e.id,
                e.cliente_id
            FROM expedientes e
            WHERE e.id = ?
            """,
            (
                expediente_id,
            ),
        ).fetchone()

        if not expediente:
            raise ValueError(
                "Expediente no encontrado"
            )

        cliente_id = int(
            expediente["cliente_id"]
        )

        metadata = (
            data.get("metadata_documento")
            or {}
        )

        cur = conn.execute(
            """
            INSERT INTO expediente_justificantes (
                expediente_id,
                cliente_id,
                archivo_nombre,
                archivo_ruta,
                tipo_justificante,
                fecha_presentacion,
                numero_registro,
                organo_presentacion,
                fecha_documento,
                csv_documento,
                dir3_documento,
                organo_documento,
                nie_documento,
                numero_expediente_documento,
                metadata_documento_json,
                procedimiento_detectado,
                estado_conciliacion,
                observaciones,
                activo
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, 1
            )
            """,
            (
                expediente_id,
                cliente_id,
                _raw(
                    data.get(
                        "archivo_nombre"
                    )
                ),
                _raw(
                    data.get(
                        "archivo_ruta"
                    )
                ),
                _text(
                    data.get(
                        "tipo_justificante"
                    )
                    or "PRESENTACION"
                ),
                _raw(
                    data.get(
                        "fecha_presentacion"
                    )
                ),
                _text(
                    data.get(
                        "numero_registro"
                    )
                ),
                _text(
                    data.get(
                        "organo_presentacion"
                    )
                ),
                _raw(
                    data.get(
                        "fecha_documento"
                    )
                ),
                _raw(
                    data.get(
                        "csv_documento"
                    )
                ),
                _text(
                    data.get(
                        "dir3_documento"
                    )
                ),
                _raw(
                    data.get(
                        "organo_documento"
                    )
                ),
                _text(
                    data.get(
                        "nie_documento"
                    )
                ),
                _text(
                    data.get(
                        "numero_expediente_documento"
                    )
                ),
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                ),
                _text(
                    data.get(
                        "procedimiento_detectado"
                    )
                ),
                _text(
                    data.get(
                        "estado_conciliacion"
                    )
                    or "PENDIENTE"
                ),
                _raw(
                    data.get(
                        "observaciones"
                    )
                ),
            ),
        )

        justificante_id = int(
            cur.lastrowid
        )

        registrar_evento(
            expediente_id=expediente_id,
            cliente_id=cliente_id,
            tipo_evento="JUSTIFICANTE",
            titulo="JUSTIFICANTE CARGADO",
            descripcion=(
                "Justificante registrado: "
                + (
                    _raw(
                        data.get(
                            "archivo_nombre"
                        )
                    )
                    or _raw(
                        data.get(
                            "archivo_ruta"
                        )
                    )
                )
            ),
            entidad_relacionada=(
                "expediente_justificantes"
            ),
            entidad_relacionada_id=(
                justificante_id
            ),
            conn=conn,
        )

        if owns_connection:
            conn.commit()

        return justificante_id

    except Exception:
        if owns_connection:
            conn.rollback()
        raise

    finally:
        if owns_connection:
            conn.close()


def get_admin_document(justificante_id):
    with _connect() as conn:
        ensure_admin_document_metadata_schema(conn)

        return _dict(
            conn.execute(
                """
                SELECT *
                FROM expediente_justificantes
                WHERE id = ?
                  AND activo = 1
                """,
                (int(justificante_id),),
            ).fetchone()
        )


def update_admin_document(
    justificante_id,
    data,
):
    import json

    justificante = get_admin_document(justificante_id)

    if not justificante:
        raise ValueError(
            "Documento administrativo no encontrado"
        )

    metadata = data.get("metadata_documento")

    if metadata is None:
        try:
            metadata = json.loads(
                justificante.get(
                    "metadata_documento_json"
                )
                or "{}"
            )
        except Exception:
            metadata = {}

    metadata_updates = (
        data.get("metadata_updates")
        or {}
    )

    with _connect() as conn:
        ensure_admin_document_metadata_schema(conn)

        current_row = conn.execute(
            """
            SELECT metadata_documento_json
            FROM expediente_justificantes
            WHERE id = ?
            """,
            (int(document_id),),
        ).fetchone()

        try:
            current_metadata = json.loads(
                (
                    current_row[
                        "metadata_documento_json"
                    ]
                    if current_row
                    else ""
                )
                or "{}"
            )
        except Exception:
            current_metadata = {}

        if not isinstance(current_metadata, dict):
            current_metadata = {}

        current_metadata.update(
            metadata_updates
        )

        data["metadata_documento_json"] = (
            json.dumps(
                current_metadata,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        conn.execute(
            """
            UPDATE expediente_justificantes
            SET
                fecha_documento = ?,
                fecha_presentacion = ?,
                csv_documento = ?,
                dir3_documento = ?,
                organo_documento = ?,
                organo_presentacion = ?,
                numero_registro = ?,
                nie_documento = ?,
                numero_expediente_documento = ?,
                observaciones = ?,
                metadata_documento_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND activo = 1
            """,
            (
                _raw(data.get("fecha_documento")),
                _raw(data.get("fecha_documento")),
                _raw(data.get("csv_documento")),
                _text(data.get("dir3_documento")),
                _raw(data.get("organo_documento")),
                _raw(data.get("organo_documento")),
                _text(data.get("numero_registro")),
                _text(data.get("nie_documento")),
                _text(
                    data.get(
                        "numero_expediente_documento"
                    )
                ),
                _raw(data.get("observaciones")),
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                ),
                int(justificante_id),
            ),
        )
        conn.commit()

    registrar_evento(
        expediente_id=justificante["expediente_id"],
        cliente_id=justificante["cliente_id"],
        tipo_evento="DOCUMENTO_ADMINISTRATIVO_EDITADO",
        titulo="DOCUMENTO ADMINISTRATIVO EDITADO",
        descripcion=(
            "Se han actualizado los metadatos del "
            f"documento #{int(justificante_id)}."
        ),
        entidad_relacionada="expediente_justificantes",
        entidad_relacionada_id=int(justificante_id),
        usuario=_raw(data.get("usuario") or "ERP"),
    )

    return get_admin_document(justificante_id)


def replace_admin_document_file(
    justificante_id,
    file_name,
    file_path,
    metadata,
):
    import json

    justificante = get_admin_document(justificante_id)

    if not justificante:
        raise ValueError(
            "Documento administrativo no encontrado"
        )

    metadata = dict(metadata or {})

    event_code = _text(
        justificante.get("tipo_justificante")
        or "OTRO"
    )

    fecha_documento = ""
    csv_documento = ""
    dir3_documento = ""
    organo_documento = ""
    numero_registro = ""
    nie_documento = ""
    numero_expediente_documento = ""

    if event_code == "JUSTIFICANTE_PRESENTACION":
        fecha_documento = (
            metadata.get("fecha_hora_presentacion")
            or metadata.get("fecha_hora_registro")
            or ""
        )
        csv_documento = (
            metadata.get("registro_csv_geiser")
            or ""
        )
        dir3_documento = (
            metadata.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )
        organo_documento = (
            metadata.get(
                "unidad_tramitacion_nombre"
            )
            or metadata.get(
                "organismo_tramitacion"
            )
            or ""
        )
        numero_registro = (
            metadata.get("numero_registro_regage")
            or ""
        )

    elif event_code in {
        "ADMISION_TRAMITE",
        "ADMISION_TRAMITE_TASA",
    }:
        fecha_documento = (
            metadata.get("fecha_admision_tramite")
            or ""
        )
        csv_documento = (
            metadata.get("csv_admision_tramite")
            or ""
        )
        dir3_documento = (
            metadata.get(
                "unidad_tramitacion_codigo"
            )
            or justificante.get("dir3_documento")
            or ""
        )
        organo_documento = (
            justificante.get("organo_documento")
            or justificante.get(
                "organo_presentacion"
            )
            or ""
        )
        nie_documento = (
            metadata.get("nie_detectado")
            or ""
        )
        numero_expediente_documento = (
            metadata.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

    with _connect() as conn:
        ensure_admin_document_metadata_schema(conn)

        conn.execute(
            """
            UPDATE expediente_justificantes
            SET
                archivo_nombre = ?,
                archivo_ruta = ?,
                fecha_documento = ?,
                fecha_presentacion = ?,
                csv_documento = ?,
                dir3_documento = ?,
                organo_documento = ?,
                organo_presentacion = ?,
                numero_registro = ?,
                nie_documento = ?,
                numero_expediente_documento = ?,
                metadata_documento_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND activo = 1
            """,
            (
                _raw(file_name),
                _raw(file_path),
                _raw(fecha_documento),
                _raw(fecha_documento),
                _raw(csv_documento),
                _text(dir3_documento),
                _raw(organo_documento),
                _raw(organo_documento),
                _text(numero_registro),
                _text(nie_documento),
                _text(numero_expediente_documento),
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                ),
                int(justificante_id),
            ),
        )
        conn.commit()

    registrar_evento(
        expediente_id=justificante["expediente_id"],
        cliente_id=justificante["cliente_id"],
        tipo_evento="DOCUMENTO_ADMINISTRATIVO_RECARGADO",
        titulo="DOCUMENTO ADMINISTRATIVO RECARGADO",
        descripcion=(
            f"Se ha reemplazado el archivo del documento "
            f"#{int(justificante_id)} por "
            f"{_raw(file_name) or _raw(file_path)}."
        ),
        entidad_relacionada="expediente_justificantes",
        entidad_relacionada_id=int(justificante_id),
        usuario="ERP",
    )

    return get_admin_document(justificante_id)


def _derive_admin_state_from_documents(
    documents,
    workflow_code,
):
    """
    Calcula el estado administrativo resultante recorriendo los
    documentos activos en el orden en que fueron incorporados.

    Los documentos sin transición administrativa se ignoran.
    El último documento que produzca transición determina el estado.
    """
    target_state = ""
    target_event_code = ""

    for document in documents or []:
        event_code = _text(
            document.get("tipo_justificante")
            if isinstance(document, dict)
            else document["tipo_justificante"]
        )

        state_name = _get_admin_document_target_state(
            event_code,
            workflow_code,
        )

        if not state_name:
            continue

        target_state = _text(state_name)
        target_event_code = event_code

    return {
        "estado_nuevo": target_state,
        "event_code_origen": target_event_code,
    }


def _get_admin_traceability_initial_state(
    conn,
    expediente_id,
):
    """
    Recupera el estado existente antes de la primera transición
    documental administrativa registrada para el expediente.
    """
    row = conn.execute(
        """
        SELECT estado_anterior
        FROM expediente_eventos
        WHERE expediente_id = ?
          AND tipo_evento = 'DOCUMENTO_ADMINISTRATIVO'
          AND entidad_relacionada = 'expediente_justificantes'
          AND NULLIF(TRIM(COALESCE(estado_anterior, '')), '') IS NOT NULL
        ORDER BY fecha_evento ASC, id ASC
        LIMIT 1
        """,
        (int(expediente_id),),
    ).fetchone()

    if row:
        initial_state = _text(row["estado_anterior"])
        if initial_state:
            return initial_state

    # Respaldo para expedientes antiguos sin evento histórico completo.
    return "NO PRESENTADO"


def _recalculate_admin_state_after_document_archive(
    conn,
    expediente_id,
    archived_event_code,
):
    """
    Recalcula el estado del expediente tras archivar una card.

    Solo se recalcula cuando la card eliminada tenía una transición
    administrativa. Eliminar documentos informativos no altera el estado.
    """
    expediente = conn.execute(
        """
        SELECT
            id,
            cliente_id,
            estado_administrativo_id,
            estado_presentacion
        FROM expedientes
        WHERE id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not expediente:
        raise ValueError("Expediente no encontrado")

    workflow_code = _resolve_expediente_workflow_code(
        conn,
        expediente_id,
    )

    archived_target_state = _get_admin_document_target_state(
        archived_event_code,
        workflow_code,
    )

    estado_anterior = _get_estado_administrativo_nombre(
        conn,
        expediente["estado_administrativo_id"],
    )

    # Una card sin transición no interviene en el estado administrativo.
    if not archived_target_state:
        return {
            "changed": False,
            "workflow_code": workflow_code,
            "estado_anterior": estado_anterior,
            "estado_nuevo": estado_anterior,
            "estado_nuevo_id":
                expediente["estado_administrativo_id"],
            "event_code_origen": "",
            "reason": "DOCUMENTO_SIN_TRANSICION",
        }

    rows = conn.execute(
        """
        SELECT
            id,
            tipo_justificante,
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

    documents = [
        dict(row)
        for row in rows
    ]

    derived = _derive_admin_state_from_documents(
        documents,
        workflow_code,
    )

    estado_nuevo = (
        derived.get("estado_nuevo")
        or _get_admin_traceability_initial_state(
            conn,
            expediente_id,
        )
    )

    estado_nuevo_id = _get_estado_administrativo_id(
        conn,
        estado_nuevo,
    )

    if not estado_nuevo_id:
        raise ValueError(
            "No existe el estado administrativo "
            f"'{estado_nuevo}' en la configuración"
        )

    changed = (
        int(expediente["estado_administrativo_id"] or 0)
        != int(estado_nuevo_id)
    )

    # estado_presentacion se basa en que siga existiendo al menos
    # un justificante de presentación activo. Solo se revisa cuando
    # se elimina una card de presentación.
    if _text(archived_event_code) == "JUSTIFICANTE_PRESENTACION":
        presentation_row = conn.execute(
            """
            SELECT id
            FROM expediente_justificantes
            WHERE expediente_id = ?
              AND activo = 1
              AND tipo_justificante = 'JUSTIFICANTE_PRESENTACION'
            LIMIT 1
            """,
            (int(expediente_id),),
        ).fetchone()

        estado_presentacion = (
            "PRESENTADO"
            if presentation_row
            else "NO PRESENTADO"
        )

        conn.execute(
            """
            UPDATE expedientes
            SET estado_administrativo_id = ?,
                estado_presentacion = ?,
                fecha_presentacion = CASE
                    WHEN ? = 'NO PRESENTADO'
                    THEN NULL
                    ELSE fecha_presentacion
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(estado_nuevo_id),
                estado_presentacion,
                estado_presentacion,
                int(expediente_id),
            ),
        )
    else:
        conn.execute(
            """
            UPDATE expedientes
            SET estado_administrativo_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(estado_nuevo_id),
                int(expediente_id),
            ),
        )

    return {
        "changed": changed,
        "workflow_code": workflow_code,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "estado_nuevo_id": int(estado_nuevo_id),
        "event_code_origen":
            derived.get("event_code_origen") or "",
        "reason":
            (
                "ULTIMO_DOCUMENTO_ACTIVO"
                if derived.get("estado_nuevo")
                else "ESTADO_INICIAL"
            ),
    }


def recalculate_expedient_admin_state(
    expediente_id,
    usuario="ERP",
):
    """
    Reconstruye el estado administrativo desde todos los documentos
    activos del expediente.

    Puede utilizarse después de un archivado o para reparar expedientes
    cuyo estado histórico haya quedado desincronizado.
    """
    expediente_id = int(expediente_id)

    with closing(
        _connect()
    ) as conn:
        expediente = conn.execute(
            """
            SELECT
                id,
                cliente_id,
                estado_administrativo_id,
                estado_presentacion
            FROM expedientes
            WHERE id = ?
            """,
            (expediente_id,),
        ).fetchone()

        if not expediente:
            raise ValueError("Expediente no encontrado")

        workflow_code = _resolve_expediente_workflow_code(
            conn,
            expediente_id,
        )

        estado_anterior = _get_estado_administrativo_nombre(
            conn,
            expediente["estado_administrativo_id"],
        )

        rows = conn.execute(
            """
            SELECT
                id,
                tipo_justificante,
                fecha_documento,
                fecha_presentacion,
                created_at
            FROM expediente_justificantes
            WHERE expediente_id = ?
              AND activo = 1
            ORDER BY
                created_at ASC,
                id ASC
            """,
            (expediente_id,),
        ).fetchall()

        documents = [
            dict(row)
            for row in rows
        ]

        derived = _derive_admin_state_from_documents(
            documents,
            workflow_code,
        )

        estado_nuevo = (
            derived.get("estado_nuevo")
            or _get_admin_traceability_initial_state(
                conn,
                expediente_id,
            )
        )

        estado_nuevo_id = _get_estado_administrativo_id(
            conn,
            estado_nuevo,
        )

        if not estado_nuevo_id:
            raise ValueError(
                "No existe el estado administrativo "
                f"'{estado_nuevo}' en configuración"
            )

        presentation_exists = conn.execute(
            """
            SELECT 1
            FROM expediente_justificantes
            WHERE expediente_id = ?
              AND activo = 1
              AND tipo_justificante = 'JUSTIFICANTE_PRESENTACION'
            LIMIT 1
            """,
            (expediente_id,),
        ).fetchone()

        estado_presentacion = (
            "PRESENTADO"
            if presentation_exists
            else "NO PRESENTADO"
        )

        changed = (
            int(expediente["estado_administrativo_id"] or 0)
            != int(estado_nuevo_id)
            or str(
                expediente["estado_presentacion"] or ""
            ).strip().upper()
            != estado_presentacion
        )

        conn.execute(
            """
            UPDATE expedientes
            SET estado_administrativo_id = ?,
                estado_presentacion = ?,
                fecha_presentacion = CASE
                    WHEN ? = 'NO PRESENTADO'
                    THEN NULL
                    ELSE fecha_presentacion
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                int(estado_nuevo_id),
                estado_presentacion,
                estado_presentacion,
                expediente_id,
            ),
        )

        conn.commit()

    return {
        "changed": changed,
        "expediente_id": expediente_id,
        "workflow_code": workflow_code,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "estado_nuevo_id": int(estado_nuevo_id),
        "estado_presentacion": estado_presentacion,
        "event_code_origen":
            derived.get("event_code_origen") or "",
        "active_document_count": len(documents),
    }


def archive_admin_document(justificante_id):
    """
    Retira una card de la trazabilidad y recalcula dentro de la misma
    transacción el estado administrativo del expediente.
    """
    justificante_id = int(justificante_id)

    with closing(
        _connect()
    ) as conn:
        justificante = conn.execute(
            """
            SELECT *
            FROM expediente_justificantes
            WHERE id = ?
              AND activo = 1
            """,
            (justificante_id,),
        ).fetchone()

        if not justificante:
            raise ValueError(
                "Documento administrativo no encontrado "
                "o ya eliminado"
            )

        justificante = dict(justificante)

        expediente_id = int(
            justificante["expediente_id"]
        )
        cliente_id = int(
            justificante["cliente_id"]
        )
        event_code = _text(
            justificante.get("tipo_justificante")
        )

        try:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                """
                UPDATE expediente_justificantes
                SET activo = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND activo = 1
                """,
                (justificante_id,),
            )

            transition = (
                _recalculate_admin_state_after_document_archive(
                    conn,
                    expediente_id,
                    event_code,
                )
            )

            event_label = (
                ADMIN_DOCUMENT_EVENT_LABELS.get(
                    event_code,
                    event_code.replace("_", " ").title(),
                )
            )

            estado_anterior = (
                transition.get("estado_anterior")
                or ""
            )
            estado_nuevo = (
                transition.get("estado_nuevo")
                or ""
            )

            transition_text = ""

            if transition.get("changed"):
                transition_text = (
                    "\nReversión administrativa: "
                    f"{estado_anterior or 'SIN ESTADO'} "
                    f"→ {estado_nuevo or 'SIN ESTADO'}."
                )
            elif transition.get("reason") == "DOCUMENTO_SIN_TRANSICION":
                transition_text = (
                    "\nEl documento no modificaba el estado "
                    "administrativo."
                )
            else:
                transition_text = (
                    "\nEl estado administrativo se mantiene en "
                    f"{estado_nuevo or estado_anterior or 'SIN ESTADO'}."
                )

            conn.execute(
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
                    expediente_id,
                    cliente_id,
                    "DOCUMENTO_ADMINISTRATIVO_ELIMINADO",
                    (
                        "DOCUMENTO ADMINISTRATIVO ELIMINADO · "
                        + event_label
                    ),
                    (
                        "Se ha retirado de la trazabilidad el "
                        f"documento #{justificante_id}: "
                        f"{justificante.get('archivo_nombre') or '-'}."
                        + transition_text
                    ),
                    estado_anterior,
                    estado_nuevo,
                    "expediente_justificantes",
                    justificante_id,
                    "ERP",
                ),
            )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

    # Segundo recálculo completo tras confirmar el archivado.
    # Actúa como garantía ante datos históricos desincronizados.
    final_transition = recalculate_expedient_admin_state(
        expediente_id,
        usuario="ERP",
    )

    transition = final_transition

    notification_tracking = None

    try:
        from backend.services import (
            notification_tracking_service
        )

        notification_tracking = (
            notification_tracking_service
            .reconcile_expedient(
                expediente_id,
                source=(
                    "ARCHIVE_ADMIN_DOCUMENT:"
                    + event_code
                ),
                usuario="ERP",
            )
        )

    except Exception as exc:
        notification_tracking = {
            "ok": False,
            "changed": False,
            "error": str(exc),
        }

    calendar_tracking = (
        _project_tracking_to_calendar(
            notification_tracking
        )
    )

    calendar_tasks = (
        _project_admin_event_tasks_to_calendar(
            expediente_id,
            event_code,
            document_id=justificante_id,
        )
    )

    return {
        "ok": True,
        "justificante_id": justificante_id,
        "expediente_id": expediente_id,
        "event_code": event_code,
        "state_recalculation": transition,
        "notification_tracking":
            notification_tracking,
        "calendar_tracking":
            calendar_tracking,
        "calendar_tasks":
            calendar_tasks,
        "estado_anterior":
            transition.get("estado_anterior") or "",
        "estado_nuevo":
            transition.get("estado_nuevo") or "",
        "state_changed":
            bool(transition.get("changed")),
    }


def conciliar_justificante(justificante_id, actualizar_expediente=True):
    with _connect() as conn:
        justificante = _dict(
            conn.execute(
                "SELECT * FROM expediente_justificantes WHERE id = ?",
                (int(justificante_id),),
            ).fetchone()
        )

        if not justificante:
            raise ValueError("Justificante no encontrado")

        conn.execute(
            """
            UPDATE expediente_justificantes
            SET estado_conciliacion = 'CONCILIADO',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(justificante_id),),
        )

        if actualizar_expediente:
            conn.execute(
                """
                UPDATE expedientes
                SET fecha_presentacion = COALESCE(?, fecha_presentacion),
                    numero_registro = COALESCE(NULLIF(?, ''), numero_registro),
                    organo_presentacion = COALESCE(NULLIF(?, ''), organo_presentacion),
                    estado_presentacion = 'PRESENTADO',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    justificante.get("fecha_presentacion"),
                    justificante.get("numero_registro") or "",
                    justificante.get("organo_presentacion") or "",
                    justificante["expediente_id"],
                ),
            )

        conn.commit()

    registrar_evento(
        expediente_id=justificante["expediente_id"],
        cliente_id=justificante["cliente_id"],
        tipo_evento="CONCILIACION_DOCUMENTAL",
        titulo="JUSTIFICANTE CONCILIADO",
        descripcion="El justificante queda vinculado al expediente presentado.",
        estado_anterior="PENDIENTE",
        estado_nuevo="CONCILIADO",
        entidad_relacionada="expediente_justificantes",
        entidad_relacionada_id=justificante_id,
    )


def get_justificantes_expediente(expediente_id):
    with _connect() as conn:
        return [
            _dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM expediente_justificantes
                WHERE expediente_id = ? AND activo = 1
                ORDER BY
                    CASE tipo_justificante
                        WHEN 'JUSTIFICANTE_PRESENTACION' THEN 10
                        WHEN 'ADMISION_TRAMITE' THEN 20
                        WHEN 'ADMISION_TRAMITE_TASA' THEN 21
                        WHEN 'INADMISION_TRAMITE' THEN 22
                        WHEN 'JUSTIFICANTE_APORTACION_TASA' THEN 30
                        WHEN 'REQUERIMIENTO' THEN 40
                        WHEN 'JUSTIFICANTE_AMPLIACION_PLAZO' THEN 41
                        WHEN 'JUSTIFICANTE_APORTACION_DOCUMENTACION' THEN 42
                        WHEN 'RESOLUCION_FAVORABLE' THEN 90
                        WHEN 'RESOLUCION_DENEGATORIA' THEN 91
                        WHEN 'RESOLUCION_DESFAVORABLE' THEN 91
                        ELSE 80
                    END ASC,
                    COALESCE(
                        NULLIF(fecha_documento, ''),
                        NULLIF(fecha_presentacion, ''),
                        created_at
                    ) ASC,
                    id ASC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]




ADMIN_DOCUMENT_EVENT_LABELS = {
    "JUSTIFICANTE_PRESENTACION": "Justificante de presentación",
    "ADMISION_TRAMITE": "Admisión a trámite",
    "INADMISION_TRAMITE": "Inadmisión a trámite",
    "ADMISION_TRAMITE_TASA": "Admisión a trámite y tasa",
    "JUSTIFICANTE_APORTACION_TASA": "Justificante de aportación de tasa",
    "REQUERIMIENTO": "Requerimiento",
    "JUSTIFICANTE_APORTACION_DOCUMENTACION": "Justificante aportación documentación",
    "JUSTIFICANTE_AMPLIACION_PLAZO": "Justificante ampliación de plazo",
    "RESOLUCION_FAVORABLE": "Resolución favorable",
    "RESOLUCION_DENEGATORIA": "Resolución denegatoria",
    "RESOLUCION_DESFAVORABLE": "Resolución denegatoria",
    "OTRO": "Otro documento administrativo",
}


ADMIN_DOCUMENT_BASE_STATE_TRANSITIONS = {
    "JUSTIFICANTE_PRESENTACION": "PRESENTADO",
    "ADMISION_TRAMITE": "ADMITIDO",
    "REQUERIMIENTO": "REQUERIDO",
    "RESOLUCION_FAVORABLE": "RESUELTO FAVORABLE",
    "RESOLUCION_DENEGATORIA": "RESUELTO DENEGADO",
    "RESOLUCION_DESFAVORABLE": "RESUELTO DENEGADO",
}


ADMIN_DOCUMENT_STATE_TRANSITIONS_BY_WORKFLOW = {
    "GENERAL": ADMIN_DOCUMENT_BASE_STATE_TRANSITIONS,
    "NACIONALIDAD": ADMIN_DOCUMENT_BASE_STATE_TRANSITIONS,
    "EXTRANJERIA": {
        "JUSTIFICANTE_PRESENTACION": "PRESENTADO",
        "ADMISION_TRAMITE": "ADMITIDO",
        "INADMISION_TRAMITE": "INADMITIDO",
        "ADMISION_TRAMITE_TASA": "ADMITIDO CON TASA",
        "JUSTIFICANTE_APORTACION_TASA": "TASA APORTADA",
        "REQUERIMIENTO": "REQUERIDO",
        "JUSTIFICANTE_APORTACION_DOCUMENTACION": "REQUERIMIENTO APORTADO",
        "JUSTIFICANTE_AMPLIACION_PLAZO": "AMPLIACIÓN DE PLAZO SOLICITADA",
        "RESOLUCION_FAVORABLE": "RESUELTO FAVORABLE",
        "RESOLUCION_DENEGATORIA": "RESUELTO DENEGADO",
        "RESOLUCION_DESFAVORABLE": "RESUELTO DENEGADO",
    },
}


def _resolve_expediente_workflow_code(conn, expediente_id):
    row = conn.execute(
        """
        SELECT
            e.id,
            te.codigo AS tipo_codigo,
            te.nombre AS tipo_nombre,
            COALESCE(te.workflow_code, '') AS workflow_code
        FROM expedientes e
        LEFT JOIN config_tipos_expediente te ON te.id = e.tipo_expediente_id
        WHERE e.id = ?
        """,
        (int(expediente_id),),
    ).fetchone()

    if not row:
        return "GENERAL"

    configured = _text(row["workflow_code"])
    if configured:
        return configured

    tipo_codigo = _text(row["tipo_codigo"])
    tipo_nombre = _text(row["tipo_nombre"])
    combined = f"{tipo_codigo} {tipo_nombre}"

    if "NACIONALIDAD" in combined:
        return "NACIONALIDAD"

    if combined.strip():
        return "EXTRANJERIA"

    return "GENERAL"


def _get_admin_document_target_state(event_code, workflow_code):
    workflow = _text(workflow_code) or "GENERAL"
    transitions = ADMIN_DOCUMENT_STATE_TRANSITIONS_BY_WORKFLOW.get(
        workflow,
        ADMIN_DOCUMENT_STATE_TRANSITIONS_BY_WORKFLOW["GENERAL"],
    )
    return transitions.get(_text(event_code))



def _get_estado_administrativo_nombre(conn, estado_id):
    if not estado_id:
        return ""
    row = conn.execute(
        """
        SELECT nombre
        FROM config_estados_administrativos
        WHERE id = ?
        """,
        (int(estado_id),),
    ).fetchone()
    return _text(row["nombre"]) if row else ""


def _get_estado_administrativo_id(conn, nombre):
    nombre = _text(nombre)
    if not nombre:
        return None
    row = conn.execute(
        """
        SELECT id
        FROM config_estados_administrativos
        WHERE UPPER(TRIM(nombre)) = ?
        LIMIT 1
        """,
        (nombre,),
    ).fetchone()
    return int(row["id"]) if row else None


def _apply_admin_document_transition(
    expediente_id,
    event_code,
    conn=None,
):
    """
    Aplica la transición administrativa del documento.

    Si recibe conn, participa en la transacción superior.
    """
    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    try:
        workflow_code = (
            _resolve_expediente_workflow_code(
                conn,
                expediente_id,
            )
        )

        target_state = (
            _get_admin_document_target_state(
                event_code,
                workflow_code,
            )
        )

        if not target_state:
            return {
                "changed": False,
                "workflow_code":
                    workflow_code,
                "estado_anterior": "",
                "estado_nuevo": "",
                "estado_nuevo_id": None,
            }

        expediente = conn.execute(
            """
            SELECT
                id,
                estado_administrativo_id
            FROM expedientes
            WHERE id = ?
            """,
            (
                int(expediente_id),
            ),
        ).fetchone()

        if not expediente:
            raise ValueError(
                "Expediente no encontrado"
            )

        estado_anterior = (
            _get_estado_administrativo_nombre(
                conn,
                expediente[
                    "estado_administrativo_id"
                ],
            )
        )

        estado_nuevo_id = (
            _get_estado_administrativo_id(
                conn,
                target_state,
            )
        )

        if not estado_nuevo_id:
            return {
                "changed": False,
                "workflow_code":
                    workflow_code,
                "estado_anterior":
                    estado_anterior,
                "estado_nuevo": "",
                "estado_nuevo_id": None,
            }

        estado_nuevo = _text(
            target_state
        )

        if int(
            expediente[
                "estado_administrativo_id"
            ]
            or 0
        ) == int(estado_nuevo_id):
            return {
                "changed": False,
                "workflow_code":
                    workflow_code,
                "estado_anterior":
                    estado_anterior,
                "estado_nuevo":
                    estado_nuevo,
                "estado_nuevo_id":
                    estado_nuevo_id,
            }

        if (
            _text(event_code)
            == "JUSTIFICANTE_PRESENTACION"
        ):
            conn.execute(
                """
                UPDATE expedientes
                SET
                    estado_administrativo_id = ?,
                    estado_presentacion =
                        'PRESENTADO',
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    estado_nuevo_id,
                    int(expediente_id),
                ),
            )
        else:
            conn.execute(
                """
                UPDATE expedientes
                SET
                    estado_administrativo_id = ?,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    estado_nuevo_id,
                    int(expediente_id),
                ),
            )

        if owns_connection:
            conn.commit()

        return {
            "changed": True,
            "workflow_code":
                workflow_code,
            "estado_anterior":
                estado_anterior,
            "estado_nuevo":
                estado_nuevo,
            "estado_nuevo_id":
                estado_nuevo_id,
        }

    except Exception:
        if owns_connection:
            conn.rollback()
        raise

    finally:
        if owns_connection:
            conn.close()



def extract_admin_presentation_document(file_path):
    """
    Lee un justificante GEISER sin modificar la base de datos.
    Se usará desde la vista para la previsualización editable.
    """
    return presentation_extractor.extract_justificante_presentacion(file_path)


def persist_presentation_registry_data(
    expediente_id,
    extraction,
    conn=None,
):
    """
    Guarda los identificadores registrales del justificante.

    No escribe numero_expediente_extranjeria porque ese valor llegará
    posteriormente mediante la vigilancia del correo electrónico.
    """
    owns_connection = conn is None
    connection = conn or _connect()

    try:
        ensure_presentation_registry_runtime_schema(connection)

        connection.execute(
            """
            UPDATE expedientes
            SET numero_presentacion_registro = ?,
                fecha_hora_presentacion = ?,
                fecha_hora_registro = ?,
                numero_registro_regage = ?,
                oficina_registro_nombre = ?,
                oficina_registro_codigo = ?,
                unidad_tramitacion_nombre = ?,
                unidad_tramitacion_codigo = ?,
                organismo_tramitacion = ?,
                registro_ambito_prefijo = ?,
                registro_csv_geiser = ?,
                justificante_presentacion_sha256 = ?,
                justificante_extraction_status = ?,
                justificante_extraction_json = ?,
                justificante_extracted_at = CURRENT_TIMESTAMP,
                fecha_presentacion = COALESCE(
                    NULLIF(SUBSTR(?, 1, 10), ''),
                    fecha_presentacion
                ),
                numero_registro = COALESCE(
                    NULLIF(?, ''),
                    numero_registro
                ),
                organo_presentacion = COALESCE(
                    NULLIF(?, ''),
                    organo_presentacion
                ),
                numero_expediente_mercurio = COALESCE(
                    NULLIF(?, ''),
                    numero_expediente_mercurio
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                _raw(extraction.get("numero_presentacion_registro")),
                _raw(extraction.get("fecha_hora_presentacion")),
                _raw(extraction.get("fecha_hora_registro")),
                _raw(extraction.get("numero_registro_regage")),
                _raw(extraction.get("oficina_registro_nombre")),
                _raw(extraction.get("oficina_registro_codigo")),
                _raw(extraction.get("unidad_tramitacion_nombre")),
                _raw(extraction.get("unidad_tramitacion_codigo")),
                _raw(extraction.get("organismo_tramitacion")),
                _raw(extraction.get("registro_ambito_prefijo")),
                _raw(extraction.get("registro_csv_geiser")),
                _raw(extraction.get("sha256")),
                "CONFIRMADA",
                json.dumps(extraction, ensure_ascii=False, sort_keys=True),
                _raw(extraction.get("fecha_hora_presentacion")),
                _raw(extraction.get("numero_registro_regage")),
                _raw(extraction.get("unidad_tramitacion_nombre")),
                _raw(extraction.get("numero_presentacion_registro")),
                int(expediente_id),
            ),
        )

        if owns_connection:
            connection.commit()
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


def _normalize_residence_expiry_date(value):
    from datetime import datetime

    value = str(value or "").strip()

    if not value:
        return ""

    for date_format in (
        "%Y-%m-%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(
                value[:10],
                date_format,
            ).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return ""


def _decide_client_residence_expiry_update(
    existing_date,
    detected_date,
):
    existing = _normalize_residence_expiry_date(
        existing_date
    )
    detected = _normalize_residence_expiry_date(
        detected_date
    )

    if not detected:
        return {
            "status": "NO_VALID_DATE",
            "should_update": False,
            "existing_date": existing,
            "detected_date": "",
        }

    if not existing:
        return {
            "status": "CREATED",
            "should_update": True,
            "existing_date": "",
            "detected_date": detected,
        }

    if detected == existing:
        return {
            "status": "UNCHANGED",
            "should_update": False,
            "existing_date": existing,
            "detected_date": detected,
        }

    if detected > existing:
        return {
            "status": "UPDATED",
            "should_update": True,
            "existing_date": existing,
            "detected_date": detected,
        }

    return {
        "status": "CONFLICT_OLDER_DATE",
        "should_update": False,
        "existing_date": existing,
        "detected_date": detected,
    }


def _ensure_client_residence_expiry_schema(conn):
    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(clientes)"
        ).fetchall()
    }

    required = {
        "fecha_caducidad_residencia": "TEXT",
        "fecha_caducidad_origen": "TEXT",
        "fecha_caducidad_expediente_id": "INTEGER",
        "fecha_caducidad_documento_id": "INTEGER",
        "fecha_caducidad_actualizada_at": "TEXT",
    }

    for column_name, column_type in required.items():
        if column_name not in columns:
            conn.execute(
                f"ALTER TABLE clientes "
                f"ADD COLUMN {column_name} "
                f"{column_type}"
            )


def _update_client_residence_expiry_from_resolution(
    expediente_id,
    justificante_id,
    extraction,
    usuario="ERP",
    conn=None,
):
    extraction = dict(
        extraction or {}
    )

    detected_date = extraction.get(
        "fecha_caducidad"
    )

    owns_connection = conn is None

    if owns_connection:
        conn = _connect()

    try:
        _ensure_client_residence_expiry_schema(
            conn
        )

        row = conn.execute(
            """
            SELECT
                e.id AS expediente_id,
                e.cliente_id,
                c.fecha_caducidad_residencia
            FROM expedientes e
            JOIN clientes c
              ON c.id = e.cliente_id
            WHERE e.id = ?
            """,
            (
                int(expediente_id),
            ),
        ).fetchone()

        if not row:
            raise ValueError(
                "No existe el expediente "
                "o su cliente"
            )

        decision = (
            _decide_client_residence_expiry_update(
                row[
                    "fecha_caducidad_residencia"
                ],
                detected_date,
            )
        )

        result = {
            **decision,
            "expediente_id":
                int(expediente_id),
            "cliente_id":
                int(row["cliente_id"]),
            "justificante_id":
                int(justificante_id),
        }

        if decision["should_update"]:
            conn.execute(
                """
                UPDATE clientes
                SET
                    fecha_caducidad_residencia = ?,
                    fecha_caducidad_origen =
                        'RESOLUCION_FAVORABLE',
                    fecha_caducidad_expediente_id = ?,
                    fecha_caducidad_documento_id = ?,
                    fecha_caducidad_actualizada_at =
                        CURRENT_TIMESTAMP,
                    updated_at =
                        CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    decision[
                        "detected_date"
                    ],
                    int(expediente_id),
                    int(justificante_id),
                    int(row["cliente_id"]),
                ),
            )

            registrar_evento(
                expediente_id=(
                    expediente_id
                ),
                cliente_id=(
                    row["cliente_id"]
                ),
                tipo_evento=(
                    "CLIENTE_CADUCIDAD_"
                    "RESIDENCIA_ACTUALIZADA"
                ),
                titulo=(
                    "CADUCIDAD DE RESIDENCIA "
                    "ACTUALIZADA"
                ),
                descripcion=(
                    "La resolución favorable "
                    "actualiza la caducidad NIE/TIE "
                    "del cliente."
                ),
                estado_anterior=(
                    decision[
                        "existing_date"
                    ]
                ),
                estado_nuevo=(
                    decision[
                        "detected_date"
                    ]
                ),
                entidad_relacionada=(
                    "expediente_justificantes"
                ),
                entidad_relacionada_id=(
                    justificante_id
                ),
                usuario=usuario,
                conn=conn,
            )

        elif (
            decision["status"]
            == "CONFLICT_OLDER_DATE"
        ):
            registrar_evento(
                expediente_id=(
                    expediente_id
                ),
                cliente_id=(
                    row["cliente_id"]
                ),
                tipo_evento=(
                    "CLIENTE_CADUCIDAD_"
                    "RESIDENCIA_CONFLICTO"
                ),
                titulo=(
                    "CONFLICTO EN CADUCIDAD "
                    "DE RESIDENCIA"
                ),
                descripcion=(
                    "La fecha detectada en la "
                    "resolución es anterior a la "
                    "fecha vigente del cliente y "
                    "no se ha sobrescrito."
                ),
                estado_anterior=(
                    decision[
                        "existing_date"
                    ]
                ),
                estado_nuevo=(
                    decision[
                        "detected_date"
                    ]
                ),
                entidad_relacionada=(
                    "expediente_justificantes"
                ),
                entidad_relacionada_id=(
                    justificante_id
                ),
                usuario=usuario,
                conn=conn,
            )

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


def create_admin_document_event(data):
    """
    Registra un documento administrativo seleccionado manualmente desde la
    pestaña Trazabilidad del expediente.

    Fase 2:
    - guarda la referencia en expediente_justificantes;
    - aplica transición administrativa si el event_code tiene mapping;
    - registra evento específico en expediente_eventos con estado anterior/nuevo.
    """
    expediente_id = int(data.get("expediente_id"))
    file_path = _raw(data.get("archivo_ruta") or data.get("file_path"))
    file_name = _raw(data.get("archivo_nombre") or data.get("file_name"))
    event_code = _text(data.get("event_code") or data.get("tipo_justificante") or "OTRO")

    if event_code in {
        "RESOLUCION_DESFAVORABLE",
        "RESOLUCION_DENEGACION",
        "RESOLUCION_DENEGADA",
    }:
        event_code = "RESOLUCION_DENEGATORIA"
    observaciones = _raw(data.get("observaciones"))

    presentation_extraction = (
        data.get("presentation_extraction")
        or None
    )

    admission_extraction = (
        data.get("admission_extraction")
        or None
    )

    tax_submission_extraction = (
        data.get("tax_submission_extraction")
        or None
    )

    requirement_extraction = (
        data.get("requirement_extraction")
        or None
    )

    document_submission_extraction = (
        data.get(
            "document_submission_extraction"
        )
        or None
    )

    requirement_extension_extraction = (
        data.get(
            "requirement_extension_extraction"
        )
        or None
    )

    favorable_resolution_extraction = (
        data.get(
            "favorable_resolution_extraction"
        )
        or None
    )

    denial_resolution_extraction = (
        data.get(
            "denial_resolution_extraction"
        )
        or None
    )

    if not file_path and not file_name:
        raise ValueError("Selecciona un documento para anexar")

    expediente = get_expediente_basic(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    label = ADMIN_DOCUMENT_EVENT_LABELS.get(
        event_code,
        event_code.replace("_", " ").title(),
    )

    document_metadata = (
        presentation_extraction
        or admission_extraction
        or tax_submission_extraction
        or requirement_extraction
        or document_submission_extraction
        or requirement_extension_extraction
        or favorable_resolution_extraction
        or denial_resolution_extraction
        or {}
    )

    fecha_documento = ""
    csv_documento = ""
    dir3_documento = ""
    organo_documento = ""

    numero_registro_documento = ""
    nie_documento = ""
    numero_expediente_documento = ""

    if presentation_extraction:
        fecha_documento = (
            presentation_extraction.get(
                "fecha_hora_presentacion"
            )
            or presentation_extraction.get(
                "fecha_hora_registro"
            )
            or ""
        )

        csv_documento = (
            presentation_extraction.get(
                "registro_csv_geiser"
            )
            or ""
        )

        dir3_documento = (
            presentation_extraction.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        organo_documento = (
            presentation_extraction.get(
                "unidad_tramitacion_nombre"
            )
            or presentation_extraction.get(
                "organismo_tramitacion"
            )
            or ""
        )

        numero_registro_documento = (
            presentation_extraction.get(
                "numero_registro_regage"
            )
            or ""
        )

    elif admission_extraction:
        fecha_documento = (
            admission_extraction.get(
                "fecha_admision_tramite"
            )
            or ""
        )

        csv_documento = (
            admission_extraction.get(
                "csv_admision_tramite"
            )
            or ""
        )

        dir3_documento = (
            admission_extraction.get(
                "unidad_tramitacion_codigo"
            )
            or expediente.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        # La admisión pertenece al mismo órgano y unidad
        # tramitadora que el justificante de presentación.
        organo_documento = (
            expediente.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "organismo_tramitacion"
            )
            or expediente.get(
                "organo_presentacion"
            )
            or ""
        )

        nie_documento = (
            admission_extraction.get("nie_detectado")
            or ""
        )

        numero_expediente_documento = (
            admission_extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

    elif tax_submission_extraction:
        fecha_documento = (
            tax_submission_extraction.get(
                "fecha_registro"
            )
            or tax_submission_extraction.get(
                "fecha_presentacion"
            )
            or ""
        )

        csv_documento = (
            tax_submission_extraction.get(
                "csv_geiser"
            )
            or ""
        )

        dir3_documento = (
            expediente.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        organo_documento = (
            expediente.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "organismo_tramitacion"
            )
            or expediente.get(
                "organo_presentacion"
            )
            or ""
        )

        nie_documento = (
            tax_submission_extraction.get(
                "nie_detectado"
            )
            or ""
        )

        numero_expediente_documento = (
            tax_submission_extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

        numero_registro_documento = (
            tax_submission_extraction.get(
                "numero_registro_regage"
            )
            or ""
        )

    elif requirement_extraction:
        fecha_documento = (
            requirement_extraction.get(
                "fecha_requerimiento"
            )
            or ""
        )

        csv_documento = (
            requirement_extraction.get(
                "csv_requerimiento"
            )
            or ""
        )

        dir3_documento = (
            requirement_extraction.get(
                "unidad_tramitacion_codigo"
            )
            or expediente.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        organo_documento = (
            requirement_extraction.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "organismo_tramitacion"
            )
            or expediente.get(
                "organo_presentacion"
            )
            or ""
        )

        nie_documento = (
            requirement_extraction.get(
                "nie_detectado"
            )
            or ""
        )

        numero_expediente_documento = (
            requirement_extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

    elif document_submission_extraction:
        fecha_documento = (
            document_submission_extraction.get(
                "fecha_registro"
            )
            or document_submission_extraction.get(
                "fecha_presentacion"
            )
            or ""
        )

        csv_documento = (
            document_submission_extraction.get(
                "csv_geiser"
            )
            or ""
        )

        dir3_documento = (
            document_submission_extraction.get(
                "unidad_tramitacion_codigo"
            )
            or expediente.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        organo_documento = (
            document_submission_extraction.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "organismo_tramitacion"
            )
            or expediente.get(
                "organo_presentacion"
            )
            or ""
        )

        nie_documento = (
            document_submission_extraction.get(
                "nie_detectado"
            )
            or ""
        )

        numero_expediente_documento = (
            document_submission_extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

        numero_registro_documento = (
            document_submission_extraction.get(
                "numero_registro_regage"
            )
            or ""
        )

    elif requirement_extension_extraction:
        fecha_documento = (
            requirement_extension_extraction.get(
                "fecha_hora_registro"
            )
            or requirement_extension_extraction.get(
                "fecha_registro"
            )
            or ""
        )

        csv_documento = (
            requirement_extension_extraction.get(
                "csv_geiser"
            )
            or ""
        )

        numero_registro_documento = (
            requirement_extension_extraction.get(
                "numero_registro_regage"
            )
            or ""
        )

        dir3_documento = (
            requirement_extension_extraction.get(
                "unidad_tramitacion_codigo"
            )
            or expediente.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        organo_documento = (
            requirement_extension_extraction.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "organismo_tramitacion"
            )
            or expediente.get(
                "organo_presentacion"
            )
            or ""
        )

        nie_documento = (
            requirement_extension_extraction.get(
                "nie_detectado"
            )
            or ""
        )

        numero_expediente_documento = (
            requirement_extension_extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

    elif favorable_resolution_extraction:
        fecha_documento = (
            favorable_resolution_extraction.get(
                "fecha_resolucion"
            )
            or ""
        )

        csv_documento = (
            favorable_resolution_extraction.get(
                "csv_resolucion"
            )
            or ""
        )

        dir3_documento = (
            favorable_resolution_extraction.get(
                "unidad_tramitacion_codigo"
            )
            or expediente.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        organo_documento = (
            favorable_resolution_extraction.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "organismo_tramitacion"
            )
            or expediente.get(
                "organo_presentacion"
            )
            or ""
        )

        nie_documento = (
            favorable_resolution_extraction.get(
                "nie_detectado"
            )
            or ""
        )

        numero_expediente_documento = (
            favorable_resolution_extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

    elif denial_resolution_extraction:
        fecha_documento = (
            denial_resolution_extraction.get(
                "fecha_resolucion"
            )
            or ""
        )

        csv_documento = (
            denial_resolution_extraction.get(
                "csv_resolucion"
            )
            or ""
        )

        dir3_documento = (
            denial_resolution_extraction.get(
                "unidad_tramitacion_codigo"
            )
            or expediente.get(
                "unidad_tramitacion_codigo"
            )
            or ""
        )

        organo_documento = (
            denial_resolution_extraction.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "unidad_tramitacion_nombre"
            )
            or expediente.get(
                "organismo_tramitacion"
            )
            or expediente.get(
                "organo_presentacion"
            )
            or ""
        )

        nie_documento = (
            denial_resolution_extraction.get(
                "nie_detectado"
            )
            or ""
        )

        numero_expediente_documento = (
            denial_resolution_extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        )

    usuario = _raw(
        data.get("usuario")
        or "ERP"
    )

    authorization_transition = None
    residence_expiry_update = None

    connection = _connect()

    try:
        connection.execute(
            "BEGIN IMMEDIATE"
        )

        justificante_id = create_justificante(
            {
                "expediente_id":
                    expediente_id,
                "archivo_nombre":
                    file_name
                    or Path(file_path).name,
                "archivo_ruta":
                    file_path,
                "tipo_justificante":
                    event_code,

                # Compatibilidad con campos legacy.
                "fecha_presentacion":
                    fecha_documento,
                "numero_registro":
                    numero_registro_documento,
                "organo_presentacion":
                    organo_documento,

                # Metadatos propios del PDF.
                "fecha_documento":
                    fecha_documento,
                "csv_documento":
                    csv_documento,
                "dir3_documento":
                    dir3_documento,
                "organo_documento":
                    organo_documento,
                "nie_documento":
                    nie_documento,
                "numero_expediente_documento":
                    numero_expediente_documento,
                "metadata_documento":
                    document_metadata,

                "estado_conciliacion":
                    "PENDIENTE",
                "observaciones":
                    observaciones,
            },
            conn=connection,
        )

        if (
            event_code
            == "RESOLUCION_FAVORABLE"
            and favorable_resolution_extraction
        ):
            residence_expiry_update = (
                _update_client_residence_expiry_from_resolution(
                    expediente_id=(
                        expediente_id
                    ),
                    justificante_id=(
                        justificante_id
                    ),
                    extraction=(
                        favorable_resolution_extraction
                    ),
                    usuario=usuario,
                    conn=connection,
                )
            )

        transition = (
            _apply_admin_document_transition(
                expediente_id,
                event_code,
                conn=connection,
            )
        )

        if (
            event_code
            == "RESOLUCION_FAVORABLE"
        ):
            from backend.services import (
                client_authorization_transition_service
            )

            resolution_data = dict(
                favorable_resolution_extraction
                or {}
            )

            resolution_data.setdefault(
                "fecha_concesion",
                resolution_data.get(
                    "fecha_resolucion"
                )
                or fecha_documento
                or None,
            )

            resolution_data.setdefault(
                "fecha_vigencia_hasta",
                resolution_data.get(
                    "fecha_caducidad"
                )
                or None,
            )

            resolution_data.setdefault(
                "numero_expediente_administrativo",
                resolution_data.get(
                    "numero_expediente_extranjeria"
                )
                or numero_expediente_documento
                or None,
            )

            resolution_data.setdefault(
                "organismo_concedente",
                resolution_data.get(
                    "unidad_tramitacion_nombre"
                )
                or organo_documento
                or None,
            )

            authorization_transition = (
                client_authorization_transition_service
                .apply_favorable_resolution_to_client(
                    expediente_id=(
                        expediente_id
                    ),
                    documento_id=(
                        justificante_id
                    ),
                    resolution_data=(
                        resolution_data
                    ),
                    usuario=usuario,
                    conn=connection,
                )
            )

            authorization_transition = {
                "ok": True,
                **(
                    authorization_transition
                    or {}
                ),
            }

        transition_text = ""

        if transition.get("changed"):
            transition_text = (
                "\nTransición administrativa: "
                f"{transition.get('estado_anterior') or 'SIN ESTADO'}"
                " → "
                f"{transition.get('estado_nuevo')}"
            )

        evento_id = registrar_evento(
            expediente_id=expediente_id,
            cliente_id=(
                expediente["cliente_id"]
            ),
            tipo_evento=(
                "DOCUMENTO_ADMINISTRATIVO"
            ),
            titulo=(
                "DOCUMENTO ADMINISTRATIVO "
                f"ANEXADO · {label}"
            ),
            descripcion=(
                "Documento: "
                + str(
                    file_name
                    or Path(file_path).name
                    or file_path
                )
                + (
                    f"\nRuta: {file_path}"
                    if file_path
                    else ""
                )
                + (
                    "\nObservaciones: "
                    + str(observaciones)
                    if observaciones
                    else ""
                )
                + (
                    "\nN.º presentación: "
                    + str(
                        presentation_extraction.get(
                            "numero_presentacion_registro"
                        )
                        or "-"
                    )
                    + "\nREGAGE: "
                    + str(
                        presentation_extraction.get(
                            "numero_registro_regage"
                        )
                        or "-"
                    )
                    + "\nCSV GEISER: "
                    + str(
                        presentation_extraction.get(
                            "registro_csv_geiser"
                        )
                        or "-"
                    )
                    if presentation_extraction
                    else ""
                )
                + transition_text
            ),
            estado_anterior=(
                transition.get(
                    "estado_anterior"
                )
                or ""
            ),
            estado_nuevo=(
                transition.get(
                    "estado_nuevo"
                )
                or ""
            ),
            entidad_relacionada=(
                "expediente_justificantes"
            ),
            entidad_relacionada_id=(
                justificante_id
            ),
            usuario=usuario,
            conn=connection,
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    if (
        event_code
        == "JUSTIFICANTE_PRESENTACION"
        and presentation_extraction
    ):
        persist_presentation_registry_data(
            expediente_id,
            presentation_extraction,
        )

    transition_text = ""
    if transition.get("changed"):
        transition_text = (
            f"\nTransición administrativa: "
            f"{transition.get('estado_anterior') or 'SIN ESTADO'} → {transition.get('estado_nuevo')}"
        )

    queue_completion = None
    if event_code == "JUSTIFICANTE_PRESENTACION":
        try:
            from backend.services import presentation_queue_service

            queue_completion = presentation_queue_service.mark_presented_by_expediente(
                expediente_id,
                source="DOCUMENTO_ADMINISTRATIVO:JUSTIFICANTE_PRESENTACION",
            )
        except Exception as exc:
            queue_completion = {
                "ok": False,
                "changed": False,
                "error": str(exc),
            }

    dehu_confirmation = None

    dehu_receipt_file = (
        data.get("dehu_receipt_file")
        or None
    )

    dehu_receipt_extraction = (
        data.get("dehu_receipt_extraction")
        or None
    )

    dehu_notification = (
        data.get("dehu_notification")
        or None
    )

    if dehu_receipt_extraction:
        try:
            from backend.services.email_platform import (
                dehu_notification_service,
            )

            extracted_identifier = (
                dehu_receipt_extraction.get(
                    "dehu_identifier"
                )
                or ""
            )

            notification_identifier = (
                (
                    dehu_notification
                    or {}
                ).get(
                    "dehu_identifier"
                )
                or ""
            )

            if (
                notification_identifier
                and
                str(extracted_identifier)
                .strip()
                .lower()
                !=
                str(notification_identifier)
                .strip()
                .lower()
            ):
                raise ValueError(
                    "El identificador del resguardo "
                    "no coincide con el aviso DEHú"
                )

            dehu_confirmation = (
                dehu_notification_service
                .confirm_notification_from_traceability(
                    dehu_identifier=(
                        extracted_identifier
                    ),
                    expediente_id=expediente_id,
                    cliente_id=(
                        expediente["cliente_id"]
                    ),
                    event_code=event_code,
                    event_id=evento_id,
                    justificante_id=justificante_id,
                    receipt_file=(
                        dehu_receipt_file
                    ),
                    receipt_extraction=(
                        dehu_receipt_extraction
                    ),
                    usuario=_raw(
                        data.get("usuario")
                        or "ERP"
                    ),
                )
            )

        except Exception as exc:
            dehu_confirmation = {
                "ok": False,
                "changed": False,
                "error": str(exc),
            }

    notification_tracking = None

    try:
        from backend.services import (
            notification_tracking_service
        )

        notification_tracking = (
            notification_tracking_service
            .reconcile_expedient(
                expediente_id,
                source=(
                    "DOCUMENTO_ADMINISTRATIVO:"
                    + event_code
                ),
                usuario=_raw(
                    data.get("usuario")
                    or "ERP"
                ),
            )
        )

    except Exception as exc:
        notification_tracking = {
            "ok": False,
            "changed": False,
            "error": str(exc),
        }

    calendar_tracking = (
        _project_tracking_to_calendar(
            notification_tracking
        )
    )

    calendar_tasks = (
        _project_admin_event_tasks_to_calendar(
            expediente_id,
            event_code,
            document_id=justificante_id,
        )
    )

    derivation_evaluation = (
        _evaluate_derivations_after_admin_event(
            expediente_id=expediente_id,
            event_code=event_code,
            usuario=_raw(
                data.get("usuario")
                or "ERP"
            ),
        )
    )

    return {
        "justificante_id": justificante_id,
        "evento_id": evento_id,
        "event_code": event_code,
        "event_label": label,
        "transition_applied": bool(transition.get("changed")),
        "workflow_code": transition.get("workflow_code") or "",
        "estado_anterior": transition.get("estado_anterior") or "",
        "estado_nuevo": transition.get("estado_nuevo") or "",
        "estado_nuevo_id": transition.get("estado_nuevo_id"),
        "queue_completion": queue_completion,
        "notification_tracking":
            notification_tracking,
        "calendar_tracking":
            calendar_tracking,
        "calendar_tasks":
            calendar_tasks,
        "derivation_evaluation":
            derivation_evaluation,
        "dehu_confirmation":
            dehu_confirmation,
        "residence_expiry_update":
            residence_expiry_update,
        "authorization_transition":
            authorization_transition,
        "presentation_extraction":
            presentation_extraction,
        "admission_extraction":
            admission_extraction,
        "tax_submission_extraction":
            tax_submission_extraction,
        "requirement_extraction":
            requirement_extraction,
        "document_submission_extraction":
            document_submission_extraction,
        "requirement_extension_extraction":
            requirement_extension_extraction,
        "favorable_resolution_extraction":
            favorable_resolution_extraction,
        "denial_resolution_extraction":
            denial_resolution_extraction,
    }


def _project_tracking_to_calendar(
    notification_tracking,
):
    """
    Proyecta el resultado canónico de
    notification_tracking sobre Calendar.

    Calendar es una proyección secundaria:
    un fallo de Calendar nunca debe impedir
    registrar o recalcular la trazabilidad
    administrativa del expediente.
    """

    if not notification_tracking:
        return {
            "ok": True,
            "action": "NO_TRACKING_RESULT",
            "alert": None,
        }

    if not notification_tracking.get("ok"):
        return {
            "ok": False,
            "action": "TRACKING_UNAVAILABLE",
            "alert": None,
            "error": (
                notification_tracking.get("error")
                or ""
            ),
        }

    try:
        from backend.services import (
            calendar_tracking_producer_service
        )

        return (
            calendar_tracking_producer_service
            .sync_from_tracking_result(
                notification_tracking,
                db_path=DB_PATH,
            )
        )

    except Exception as exc:
        return {
            "ok": False,
            "action": "CALENDAR_PROJECTION_ERROR",
            "alert": None,
            "error": str(exc),
        }


def _project_admin_event_tasks_to_calendar(
    expediente_id,
    event_code,
    *,
    document_id=None,
):
    """
    Proyecta obligaciones operativas derivadas de
    documentos administrativos sobre TASK de Calendar.

    Calendar es una proyección secundaria:
    un fallo nunca invalida la trazabilidad.
    """
    normalized_event = _text(
        event_code
    )

    supported = {
        "ADMISION_TRAMITE_TASA",
        "JUSTIFICANTE_APORTACION_TASA",
        "REQUERIMIENTO",
        "JUSTIFICANTE_APORTACION_DOCUMENTACION",
    }

    if normalized_event not in supported:
        return {
            "ok": True,
            "action": "NO_APLICABLE",
            "task": None,
        }

    try:
        from backend.services import (
            calendar_traceability_task_producer_service
        )

        if normalized_event in {
            "ADMISION_TRAMITE_TASA",
            "JUSTIFICANTE_APORTACION_TASA",
        }:
            return (
                calendar_traceability_task_producer_service
                .sync_tax_obligation(
                    expediente_id,
                    db_path=DB_PATH,
                )
            )

        return (
            calendar_traceability_task_producer_service
            .sync_requirement_obligation(
                expediente_id,
                event_code=normalized_event,
                document_id=document_id,
                db_path=DB_PATH,
            )
        )

    except Exception as exc:
        return {
            "ok": False,
            "action":
                "CALENDAR_TASK_PROJECTION_ERROR",
            "task": None,
            "error": str(exc),
        }


def _evaluate_derivations_after_admin_event(
    expediente_id,
    event_code,
    usuario="ERP",
):
    """
    Evalúa las reglas de derivación después de registrar un documento
    administrativo.

    Esta proyección es secundaria: un error del motor de derivaciones
    no debe impedir que el documento o la resolución queden registrados.
    """
    normalized_event = _text(event_code)

    result_by_event = {
        "RESOLUCION_FAVORABLE": "CONCEDIDO",
        "RESOLUCION_DENEGATORIA": "DENEGADO",
    }

    required_result = result_by_event.get(
        normalized_event
    )

    try:
        from backend.services import (
            expedient_evolution_service
        )

        evaluation = (
            expedient_evolution_service
            .evaluate_derivation_rules_for_event(
                expediente_id=int(expediente_id),
                event_code=normalized_event,
                resultado=required_result,
                usuario=_raw(usuario or "ERP"),
            )
        )

        return {
            "ok": True,
            "event_code": normalized_event,
            "resultado": required_result,
            "rules_evaluated": int(
                evaluation.get(
                    "rules_evaluated",
                    0,
                )
                or 0
            ),
            "proposals": (
                evaluation.get("proposals")
                or []
            ),
            "skipped": (
                evaluation.get("skipped")
                or []
            ),
            "error": "",
        }

    except Exception as exc:
        return {
            "ok": False,
            "event_code": normalized_event,
            "resultado": required_result,
            "rules_evaluated": 0,
            "proposals": [],
            "skipped": [],
            "error": str(exc),
        }


def create_consulta_previa(data):
    cliente_id = int(data.get("cliente_id"))
    importe = _float(data.get("importe"))

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO consultas_previas (
                cliente_id, fecha_consulta, importe, forma_pago,
                profesional_responsable, descontable, estado,
                observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                cliente_id,
                _raw(data.get("fecha_consulta")),
                importe,
                _text(data.get("forma_pago")),
                _text(data.get("profesional_responsable")),
                int(data.get("descontable", 1)),
                "DISPONIBLE" if int(data.get("descontable", 1)) else "NO DESCONTABLE",
                _raw(data.get("observaciones")),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_consultas_cliente(cliente_id, only_available=False):
    sql = """
        SELECT *
        FROM consultas_previas
        WHERE cliente_id = ? AND activo = 1
    """
    params = [int(cliente_id)]

    if only_available:
        sql += " AND descontable = 1 AND estado = 'DISPONIBLE'"

    sql += " ORDER BY fecha_consulta DESC, id DESC"

    with _connect() as conn:
        return [_dict(r) for r in conn.execute(sql, params).fetchall()]


def create_hoja_encargo(data):
    expediente_id = int(data.get("expediente_id"))
    expediente = get_expediente_basic(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    cliente_id = expediente["cliente_id"]
    importe_bruto = _float(data.get("importe_bruto"))
    descuento_manual = _float(data.get("descuento_manual"))
    descuento_consultas = _float(data.get("descuento_consultas_previas"))
    importe_neto = max(0, importe_bruto - descuento_manual - descuento_consultas)

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO hojas_encargo (
                expediente_id, cliente_id, numero_hoja, fecha_firma,
                procedimiento, importe_bruto, descuento_manual,
                descuento_consultas_previas, importe_neto,
                forma_pago_pactada, numero_plazos, fecha_maxima_pago,
                documento_ruta, estado_firma, observaciones, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                expediente_id,
                cliente_id,
                _text(data.get("numero_hoja")),
                _raw(data.get("fecha_firma")),
                _text(data.get("procedimiento")),
                importe_bruto,
                descuento_manual,
                descuento_consultas,
                importe_neto,
                _text(data.get("forma_pago_pactada")),
                int(data.get("numero_plazos") or 1),
                _raw(data.get("fecha_maxima_pago")),
                _raw(data.get("documento_ruta")),
                _text(data.get("estado_firma") or "PENDIENTE FIRMA"),
                _raw(data.get("observaciones")),
            ),
        )
        hoja_id = cur.lastrowid
        conn.commit()

    registrar_evento(
        expediente_id=expediente_id,
        cliente_id=cliente_id,
        tipo_evento="HOJA_ENCARGO",
        titulo="HOJA DE ENCARGO REGISTRADA",
        descripcion=f"Importe bruto: {importe_bruto:.2f} · Neto: {importe_neto:.2f}",
        entidad_relacionada="hojas_encargo",
        entidad_relacionada_id=hoja_id,
    )

    return hoja_id


def get_hojas_encargo_expediente(expediente_id):
    with _connect() as conn:
        return [
            _dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM hojas_encargo
                WHERE expediente_id = ? AND activo = 1
                ORDER BY created_at DESC, id DESC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]


def aplicar_consulta_a_expediente(expediente_id, consulta_previa_id, hoja_encargo_id=None, importe_aplicado=None, observaciones=""):
    expediente = get_expediente_basic(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    with _connect() as conn:
        consulta = _dict(
            conn.execute(
                """
                SELECT *
                FROM consultas_previas
                WHERE id = ? AND activo = 1
                """,
                (int(consulta_previa_id),),
            ).fetchone()
        )

        if not consulta:
            raise ValueError("Consulta previa no encontrada")

        if consulta["estado"] != "DISPONIBLE":
            raise ValueError("La consulta previa no está disponible")

        if int(consulta["cliente_id"]) != int(expediente["cliente_id"]):
            raise ValueError("La consulta previa pertenece a otro cliente")

        importe = _float(importe_aplicado if importe_aplicado is not None else consulta["importe"])

        cur = conn.execute(
            """
            INSERT INTO expediente_consultas_aplicadas (
                expediente_id, cliente_id, consulta_previa_id,
                hoja_encargo_id, importe_aplicado, observaciones
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(expediente_id),
                int(expediente["cliente_id"]),
                int(consulta_previa_id),
                _int_or_none(hoja_encargo_id),
                importe,
                _raw(observaciones),
            ),
        )

        conn.execute(
            """
            UPDATE consultas_previas
            SET estado = 'APLICADA',
                expediente_id_aplicado = ?,
                fecha_aplicacion = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(expediente_id), int(consulta_previa_id)),
        )

        if hoja_encargo_id:
            conn.execute(
                """
                UPDATE hojas_encargo
                SET descuento_consultas_previas = descuento_consultas_previas + ?,
                    importe_neto = MAX(0, importe_bruto - descuento_manual - (descuento_consultas_previas + ?)),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (importe, importe, int(hoja_encargo_id)),
            )

        conn.commit()
        applied_id = cur.lastrowid

    registrar_evento(
        expediente_id=expediente_id,
        cliente_id=expediente["cliente_id"],
        tipo_evento="CONSULTA_PREVIA",
        titulo="CONSULTA PREVIA APLICADA",
        descripcion=f"Consulta previa descontada por importe {importe:.2f}",
        entidad_relacionada="expediente_consultas_aplicadas",
        entidad_relacionada_id=applied_id,
    )

    return applied_id



def ensure_expedient_notes_schema(conn=None):
    own_connection = conn is None
    connection = conn or _connect()

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS expediente_notas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expediente_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                contenido TEXT NOT NULL,
                categoria TEXT NOT NULL DEFAULT 'GENERAL',
                autor TEXT,
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (expediente_id)
                    REFERENCES expedientes(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
                idx_expediente_notas_expediente
            ON expediente_notas(
                expediente_id,
                created_at DESC
            );
            """
        )

        if own_connection:
            connection.commit()
    finally:
        if own_connection:
            connection.close()


def get_expedient_notes(expediente_id):
    connection = _connect()

    try:
        ensure_expedient_notes_schema(connection)

        rows = connection.execute(
            """
            SELECT *
            FROM expediente_notas
            WHERE expediente_id = ?
              AND activo = 1
            ORDER BY created_at DESC, id DESC
            """,
            (int(expediente_id),),
        ).fetchall()

        return [_dict(row) for row in rows]
    finally:
        connection.close()


def create_expedient_note(
    expediente_id,
    titulo,
    contenido,
    categoria="GENERAL",
    autor="ERP",
):
    # El contenido de una nota debe conservar la escritura original.
    # _text() se usa en otros puntos para normalización administrativa,
    # pero convierte a mayúsculas y no es apropiado aquí.
    titulo = str(titulo or "").strip()
    contenido = str(contenido or "").strip()
    categoria = str(categoria or "GENERAL").strip().upper()
    autor = str(autor or "ERP").strip() or "ERP"

    if not titulo:
        raise ValueError("La nota necesita un título")

    if not contenido:
        raise ValueError("La nota necesita contenido")

    connection = _connect()

    try:
        ensure_expedient_notes_schema(connection)

        expediente = connection.execute(
            """
            SELECT id, cliente_id
            FROM expedientes
            WHERE id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

        if not expediente:
            raise ValueError("No existe el expediente")

        cursor = connection.execute(
            """
            INSERT INTO expediente_notas (
                expediente_id,
                titulo,
                contenido,
                categoria,
                autor
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(expediente_id),
                titulo,
                contenido,
                categoria,
                autor,
            ),
        )

        note_id = cursor.lastrowid

        # El evento histórico se registra en la misma transacción.
        # Así la nota y su trazabilidad son atómicas y no se abre
        # una segunda conexión SQLite que pueda quedar bloqueada.
        connection.execute(
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
                int(expediente["cliente_id"]),
                "NOTA_EXPEDIENTE",
                "NOTA AÑADIDA",
                titulo,
                "expediente_notas",
                int(note_id),
                autor,
            ),
        )

        connection.commit()

        return note_id

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def archive_expedient_note(note_id):
    connection = _connect()

    try:
        ensure_expedient_notes_schema(connection)

        connection.execute(
            """
            UPDATE expediente_notas
            SET
                activo = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(note_id),),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()



def get_resumen_trazabilidad(expediente_id):
    justificantes = get_justificantes_expediente(expediente_id)
    hojas = get_hojas_encargo_expediente(expediente_id)
    eventos = get_eventos_expediente(expediente_id)

    with _connect() as conn:
        consultas_aplicadas = [
            _dict(r)
            for r in conn.execute(
                """
                SELECT a.*, c.fecha_consulta, c.importe AS importe_original
                FROM expediente_consultas_aplicadas a
                JOIN consultas_previas c ON c.id = a.consulta_previa_id
                WHERE a.expediente_id = ?
                ORDER BY a.created_at DESC
                """,
                (int(expediente_id),),
            ).fetchall()
        ]

    return {
        "justificantes": justificantes,
        "hojas_encargo": hojas,
        "consultas_aplicadas": consultas_aplicadas,
        "eventos": eventos,
        "notas": get_expedient_notes(expediente_id),
    }


ADMISSION_RUNTIME_COLUMNS = {
    "fecha_admision_tramite": "TEXT",
    "csv_admision_tramite": "TEXT",
    "admision_tramite_sha256": "TEXT",
    "admision_extraction_status": "TEXT",
    "admision_extraction_json": "TEXT",
    "admision_extracted_at": "TEXT",
}


def ensure_admission_runtime_schema(conn):
    for column_name, column_type in (
        ADMISSION_RUNTIME_COLUMNS.items()
    ):
        if not _column_exists(
            conn,
            "expedientes",
            column_name,
        ):
            conn.execute(
                f"""
                ALTER TABLE expedientes
                ADD COLUMN {column_name} {column_type}
                """
            )



def extract_admin_tax_submission_document(file_path):
    from backend.services import (
        justificante_aportacion_tasa_extraction_service
        as tax_submission_extractor,
    )

    return (
        tax_submission_extractor
        .extract_justificante_aportacion_tasa(
            file_path
        )
    )


def extract_admin_requirement_extension(
    file_path,
):
    from backend.services import (
        justificante_ampliacion_plazo_extraction_service
        as extension_extractor,
    )

    return (
        extension_extractor
        .extract_justificante_ampliacion_plazo(
            file_path
        )
    )


def extract_admin_denial_resolution(
    file_path,
):
    from backend.services import (
        resolucion_denegacion_extraction_service
        as denial_resolution_extractor,
    )

    return (
        denial_resolution_extractor
        .extract_resolucion_denegacion(
            file_path
        )
    )


def extract_admin_favorable_resolution(
    file_path,
):
    from backend.services import (
        resolucion_favorable_extraction_service
        as favorable_resolution_extractor,
    )

    return (
        favorable_resolution_extractor
        .extract_resolucion_favorable(
            file_path
        )
    )


def extract_admin_document_submission(
    file_path,
):
    from backend.services import (
        justificante_aportacion_documentacion_extraction_service
        as document_submission_extractor,
    )

    return (
        document_submission_extractor
        .extract_justificante_aportacion_documentacion(
            file_path
        )
    )


def extract_admin_requirement_document(file_path):
    from backend.services import (
        requerimiento_extraction_service
        as requirement_extractor,
    )

    return requirement_extractor.extract_requerimiento(
        file_path
    )


def extract_admin_admission_document(file_path):
    from backend.services import (
        admision_tramite_extraction_service
        as admission_extractor,
    )

    return admission_extractor.extract_admision_tramite(
        file_path
    )


def persist_admission_data(
    expediente_id,
    extraction,
):
    import json

    extraction = dict(extraction or {})
    connection = _connect()

    try:
        ensure_admission_runtime_schema(connection)

        expediente = connection.execute(
            """
            SELECT
                e.id,
                e.cliente_id,
                e.numero_expediente_extranjeria,
                e.fecha_admision_tramite,
                e.csv_admision_tramite,
                c.nie AS cliente_nie
            FROM expedientes e
            JOIN clientes c
              ON c.id = e.cliente_id
            WHERE e.id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

        if not expediente:
            raise ValueError(
                "No existe el expediente"
            )

        detected_nie = str(
            extraction.get("nie_detectado")
            or ""
        ).strip().upper()

        detected_expediente = str(
            extraction.get(
                "numero_expediente_extranjeria"
            )
            or ""
        ).strip()

        existing_nie = str(
            expediente["cliente_nie"]
            or ""
        ).strip().upper()

        existing_expediente = str(
            expediente[
                "numero_expediente_extranjeria"
            ]
            or ""
        ).strip()

        conflicts = []
        updates = {}

        if detected_nie:
            if not existing_nie:
                connection.execute(
                    """
                    UPDATE clientes
                    SET
                        nie = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        detected_nie,
                        int(expediente["cliente_id"]),
                    ),
                )
                updates["cliente_nie"] = detected_nie

            elif existing_nie != detected_nie:
                conflicts.append(
                    {
                        "field": "cliente_nie",
                        "existing": existing_nie,
                        "detected": detected_nie,
                    }
                )

        if detected_expediente:
            if not existing_expediente:
                updates[
                    "numero_expediente_extranjeria"
                ] = detected_expediente

            elif (
                existing_expediente
                != detected_expediente
            ):
                conflicts.append(
                    {
                        "field":
                            "numero_expediente_extranjeria",
                        "existing": existing_expediente,
                        "detected": detected_expediente,
                    }
                )

        status = (
            "CONFLICTO"
            if conflicts
            else "CONFIRMADA"
        )

        connection.execute(
            """
            UPDATE expedientes
            SET
                fecha_admision_tramite = ?,
                csv_admision_tramite = ?,
                admision_tramite_sha256 = ?,
                admision_extraction_status = ?,
                admision_extraction_json = ?,
                admision_extracted_at =
                    CURRENT_TIMESTAMP,
                numero_expediente_extranjeria =
                    COALESCE(
                        NULLIF(
                            numero_expediente_extranjeria,
                            ''
                        ),
                        ?
                    ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                extraction.get(
                    "fecha_admision_tramite"
                ),
                extraction.get(
                    "csv_admision_tramite"
                ),
                extraction.get("sha256"),
                status,
                json.dumps(
                    extraction,
                    ensure_ascii=False,
                ),
                (
                    detected_expediente
                    if not existing_expediente
                    else None
                ),
                int(expediente_id),
            ),
        )

        connection.commit()

        notification_tracking = None

        try:
            from backend.services import (
                notification_tracking_service
            )

            notification_tracking = (
                notification_tracking_service
                .reconcile_expedient(
                    expediente_id,
                    source="PERSIST_ADMISSION_DATA",
                    usuario="ERP",
                )
            )

        except Exception as exc:
            notification_tracking = {
                "ok": False,
                "changed": False,
                "error": str(exc),
            }

        calendar_tracking = (
            _project_tracking_to_calendar(
                notification_tracking
            )
        )

        return {
            "status": status,
            "updates": updates,
            "conflicts": conflicts,
            "extraction": extraction,
            "notification_tracking":
                notification_tracking,
            "calendar_tracking":
                calendar_tracking,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def extract_admin_dehu_receipt(file_path):
    """
    Extrae los datos técnicos de un resguardo DEHú.

    El identificador DEHú es la clave funcional que
    permite asociar el resguardo con una notificación
    concreta.
    """
    from backend.services.dehu_receipt_extraction_service import (
        extract_dehu_receipt,
    )

    return extract_dehu_receipt(file_path)
