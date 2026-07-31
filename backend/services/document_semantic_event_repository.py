"""
Persistencia de snapshots y eventos documentales semánticos.

Responsabilidades:
- cargar el último snapshot de un expediente;
- actualizar el snapshot actual;
- registrar eventos de forma idempotente;
- listar eventos técnicos.

No diagnostica expedientes.
No abre ni escanea Box.
No crea notificaciones visibles.
"""

import json
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "20260731_create_document_semantic_events.sql"
)


def _connect(db_path=None):
    path = Path(db_path or DEFAULT_DB_PATH)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


def _dict(row):
    return dict(row) if row else None


def ensure_schema(
    *,
    conn=None,
    db_path=None,
):
    """
    Aplica la migración de forma idempotente.

    Si se proporciona conexión, no la cierra.
    """
    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        sql = MIGRATION_PATH.read_text(
            encoding="utf-8"
        )
        connection.executescript(sql)

        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def get_snapshot(
    expediente_id,
    *,
    conn=None,
    db_path=None,
):
    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        row = connection.execute(
            """
            SELECT *
            FROM document_semantic_snapshots
            WHERE expediente_id = ?
            """,
            (int(expediente_id),),
        ).fetchone()

        result = _dict(row)

        if result:
            try:
                result["diagnosis"] = json.loads(
                    result.get(
                        "diagnosis_json"
                    )
                    or "{}"
                )
            except json.JSONDecodeError:
                result["diagnosis"] = {}

        return result
    finally:
        if owns_connection:
            connection.close()


def upsert_snapshot(
    snapshot,
    *,
    source_type="MANUAL_DIAGNOSIS",
    source_scan_run_id=None,
    source_scan_job_id=None,
    conn=None,
    db_path=None,
):
    """
    Inserta o sustituye el snapshot actual del expediente.
    """
    if not snapshot:
        raise ValueError(
            "El snapshot es obligatorio"
        )

    expediente_id = int(
        snapshot.get("expediente_id") or 0
    )

    if not expediente_id:
        raise ValueError(
            "El snapshot no contiene expediente_id"
        )

    fingerprint = str(
        snapshot.get("fingerprint") or ""
    ).strip()

    if not fingerprint:
        raise ValueError(
            "El snapshot no contiene fingerprint"
        )

    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        connection.execute(
            """
            INSERT INTO document_semantic_snapshots (
                expediente_id,
                estado_documental,
                estado_procesal,
                estado_combinado,
                semantico_aplicable,
                motor_activo,
                grupos_bloqueantes,
                ambiguedades_rol,
                fingerprint,
                diagnosis_json,
                source_type,
                source_scan_run_id,
                source_scan_job_id,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(expediente_id)
            DO UPDATE SET
                estado_documental = excluded.estado_documental,
                estado_procesal = excluded.estado_procesal,
                estado_combinado = excluded.estado_combinado,
                semantico_aplicable = excluded.semantico_aplicable,
                motor_activo = excluded.motor_activo,
                grupos_bloqueantes = excluded.grupos_bloqueantes,
                ambiguedades_rol = excluded.ambiguedades_rol,
                fingerprint = excluded.fingerprint,
                diagnosis_json = excluded.diagnosis_json,
                source_type = excluded.source_type,
                source_scan_run_id = excluded.source_scan_run_id,
                source_scan_job_id = excluded.source_scan_job_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                expediente_id,
                snapshot.get(
                    "estado_documental"
                )
                or "SIN_DIAGNOSTICO",
                snapshot.get(
                    "estado_procesal"
                ),
                snapshot.get(
                    "estado_combinado"
                ),
                1
                if snapshot.get(
                    "semantico_aplicable"
                )
                else 0,
                snapshot.get("motor_activo"),
                int(
                    snapshot.get(
                        "grupos_bloqueantes"
                    )
                    or 0
                ),
                int(
                    snapshot.get(
                        "ambiguedades_rol"
                    )
                    or 0
                ),
                fingerprint,
                snapshot.get(
                    "diagnosis_json"
                )
                or "{}",
                str(
                    source_type
                    or "MANUAL_DIAGNOSIS"
                ),
                (
                    int(source_scan_run_id)
                    if source_scan_run_id
                    else None
                ),
                (
                    int(source_scan_job_id)
                    if source_scan_job_id
                    else None
                ),
            ),
        )

        if owns_connection:
            connection.commit()

        return get_snapshot(
            expediente_id,
            conn=connection,
        )
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


def insert_event(
    event,
    *,
    source_type="MANUAL_DIAGNOSIS",
    source_scan_run_id=None,
    source_scan_job_id=None,
    title=None,
    description=None,
    severity="INFO",
    metadata=None,
    conn=None,
    db_path=None,
):
    """
    Registra un evento mediante INSERT OR IGNORE.

    Devuelve:
    - created=True si se insertó;
    - created=False si la clave idempotente ya existía.
    """
    if not event:
        raise ValueError(
            "El evento es obligatorio"
        )

    expediente_id = int(
        event.get("expediente_id") or 0
    )

    if not expediente_id:
        raise ValueError(
            "El evento no contiene expediente_id"
        )

    event_type = str(
        event.get("event_type") or ""
    ).strip()

    if not event_type:
        raise ValueError(
            "El evento no contiene event_type"
        )

    idempotency_key = str(
        event.get("idempotency_key") or ""
    ).strip()

    if not idempotency_key:
        raise ValueError(
            "El evento no contiene idempotency_key"
        )

    new_fingerprint = str(
        event.get("new_fingerprint") or ""
    ).strip()

    if not new_fingerprint:
        raise ValueError(
            "El evento no contiene new_fingerprint"
        )

    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO
            document_semantic_events (
                expediente_id,
                cliente_id,
                event_type,
                severity,
                previous_document_state,
                new_document_state,
                previous_process_state,
                new_process_state,
                previous_fingerprint,
                new_fingerprint,
                idempotency_key,
                source_type,
                source_scan_run_id,
                source_scan_job_id,
                title,
                description,
                metadata_json,
                status
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, 'OPEN'
            )
            """,
            (
                expediente_id,
                (
                    int(event["cliente_id"])
                    if event.get("cliente_id")
                    else None
                ),
                event_type,
                str(severity or "INFO"),
                event.get(
                    "previous_document_state"
                ),
                event.get(
                    "new_document_state"
                ),
                event.get(
                    "previous_process_state"
                ),
                event.get(
                    "new_process_state"
                ),
                event.get(
                    "previous_fingerprint"
                ),
                new_fingerprint,
                idempotency_key,
                str(
                    source_type
                    or "MANUAL_DIAGNOSIS"
                ),
                (
                    int(source_scan_run_id)
                    if source_scan_run_id
                    else None
                ),
                (
                    int(source_scan_job_id)
                    if source_scan_job_id
                    else None
                ),
                title
                or event_type.replace(
                    "_",
                    " ",
                ).title(),
                description,
                json.dumps(
                    metadata or {},
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            ),
        )

        created = cursor.rowcount == 1

        row = connection.execute(
            """
            SELECT *
            FROM document_semantic_events
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()

        if owns_connection:
            connection.commit()

        return {
            "created": created,
            "event": _dict(row),
        }
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()


def list_events(
    *,
    expediente_id=None,
    status=None,
    limit=100,
    conn=None,
    db_path=None,
):
    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        where = []
        params = []

        if expediente_id:
            where.append(
                "expediente_id = ?"
            )
            params.append(int(expediente_id))

        if status:
            where.append("status = ?")
            params.append(str(status))

        where_sql = (
            "WHERE " + " AND ".join(where)
            if where
            else ""
        )

        params.append(
            max(1, min(int(limit), 1000))
        )

        rows = connection.execute(
            f"""
            SELECT *
            FROM document_semantic_events
            {where_sql}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [_dict(row) for row in rows]
    finally:
        if owns_connection:
            connection.close()


def resolve_event(
    event_id,
    *,
    conn=None,
    db_path=None,
):
    owns_connection = conn is None
    connection = conn or _connect(db_path)

    try:
        cursor = connection.execute(
            """
            UPDATE document_semantic_events
            SET
                status = 'RESOLVED',
                resolved_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status <> 'RESOLVED'
            """,
            (int(event_id),),
        )

        if owns_connection:
            connection.commit()

        return cursor.rowcount == 1
    except Exception:
        if owns_connection:
            connection.rollback()
        raise
    finally:
        if owns_connection:
            connection.close()
