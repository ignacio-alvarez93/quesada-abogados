"""
Servicio de cola de presentación asistida.

Fase 2:
- Encolar expedientes.
- Listar cola.
- Ejecutar un expediente de forma individual usando el servicio actual.
- Al ejecutar, marcar como lanzado, no como completado.
- Permitir marcar manualmente como presentado/completado.
- Registrar trazabilidad al lanzar y al marcar presentado.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

from backend.services import presentation_assistant_service
from backend.services import expedient_traceability_service as trace_service

DB_PATH = Path(__file__).resolve().parents[2] / "database" / "quesada.db"

QUEUE_PENDING = "pendiente"
QUEUE_RUNNING = "en_proceso"
QUEUE_LAUNCHED = "lanzado"
QUEUE_DONE = "completado"
QUEUE_ERROR = "error"
QUEUE_CANCELLED = "cancelado"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dict(row):
    return dict(row) if row else None


def ensure_schema():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS presentation_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expediente_id INTEGER NOT NULL,
                numero_expediente TEXT,
                cliente_nombre TEXT,
                tipo_expediente TEXT,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                prioridad INTEGER NOT NULL DEFAULT 0,
                intentos INTEGER NOT NULL DEFAULT 0,
                pid INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                UNIQUE(expediente_id, estado)
            )
            """
        )

        existing_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(presentation_queue)").fetchall()
        }

        required_columns = {
            "numero_expediente": "TEXT",
            "cliente_nombre": "TEXT",
            "tipo_expediente": "TEXT",
            "estado": "TEXT NOT NULL DEFAULT 'pendiente'",
            "prioridad": "INTEGER NOT NULL DEFAULT 0",
            "intentos": "INTEGER NOT NULL DEFAULT 0",
            "pid": "INTEGER",
            "last_error": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
            "started_at": "TEXT",
            "finished_at": "TEXT",
        }

        for column, definition in required_columns.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE presentation_queue ADD COLUMN {column} {definition}")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_presentation_queue_estado
            ON presentation_queue(estado, prioridad, created_at)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _connect():
    ensure_schema()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _register_trace(expediente_id, tipo_evento, titulo, descripcion):
    try:
        expediente = get_expediente_for_queue(expediente_id)
        if not expediente or not expediente.get("cliente_id"):
            return

        trace_service.registrar_evento(
            expediente_id=int(expediente_id),
            cliente_id=expediente.get("cliente_id"),
            tipo_evento=tipo_evento,
            titulo=titulo,
            descripcion=descripcion,
            entidad_relacionada="expedientes",
            entidad_relacionada_id=int(expediente_id),
            usuario="ERP",
        )
    except Exception:
        # La trazabilidad no debe bloquear la cola.
        pass


def get_expediente_for_queue(expediente_id):
    with _connect() as conn:
        return _dict(
            conn.execute(
                """
                SELECT
                    e.id,
                    e.numero_expediente,
                    e.tipo_expediente_id,
                    e.cliente_id,
                    e.box_folder_path,
                    COALESCE(c.nombre, '') || ' ' || COALESCE(c.primer_apellido, '') || ' ' || COALESCE(c.segundo_apellido, '') AS cliente_nombre,
                    COALESCE(t.nombre, t.codigo, '') AS tipo_expediente
                FROM expedientes e
                LEFT JOIN clientes c ON c.id = e.cliente_id
                LEFT JOIN config_tipos_expediente t ON t.id = e.tipo_expediente_id
                WHERE e.id = ?
                """,
                (int(expediente_id),),
            ).fetchone()
        )


def enqueue_expediente(expediente_id, prioridad=0):
    expediente = get_expediente_for_queue(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    now = _now()

    with _connect() as conn:
        existing = conn.execute(
            """
            SELECT id, estado
            FROM presentation_queue
            WHERE expediente_id = ?
              AND estado IN ('pendiente', 'en_proceso', 'lanzado')
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(expediente_id),),
        ).fetchone()

        if existing:
            return {
                "created": False,
                "id": existing["id"],
                "estado": existing["estado"],
                "message": "El expediente ya está en cola o lanzado",
            }

        cur = conn.execute(
            """
            INSERT INTO presentation_queue (
                expediente_id,
                numero_expediente,
                cliente_nombre,
                tipo_expediente,
                estado,
                prioridad,
                intentos,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                int(expediente_id),
                expediente.get("numero_expediente"),
                (expediente.get("cliente_nombre") or "").strip(),
                expediente.get("tipo_expediente"),
                QUEUE_PENDING,
                int(prioridad or 0),
                now,
                now,
            ),
        )
        conn.commit()

    _register_trace(
        expediente_id,
        "COLA_PRESENTACION",
        "EXPEDIENTE ENVIADO A COLA DE PRESENTACION",
        "El expediente se incorpora a la cola de presentación asistida.",
    )

    return {
        "created": True,
        "id": cur.lastrowid,
        "estado": QUEUE_PENDING,
        "message": "Expediente enviado a cola",
    }


def list_queue(estado=None, limit=200):
    params = []
    where = ""

    if estado and estado != "todos":
        where = "WHERE q.estado = ?"
        params.append(str(estado))

    params.append(int(limit or 200))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                q.*,
                e.cliente_id,
                e.tipo_expediente_id,
                e.box_folder_path
            FROM presentation_queue q
            LEFT JOIN expedientes e ON e.id = q.expediente_id
            {where}
            ORDER BY
                CASE q.estado
                    WHEN 'en_proceso' THEN 0
                    WHEN 'pendiente' THEN 1
                    WHEN 'lanzado' THEN 2
                    WHEN 'error' THEN 3
                    WHEN 'completado' THEN 4
                    ELSE 5
                END,
                q.prioridad DESC,
                q.created_at ASC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def get_queue_item(queue_id):
    with _connect() as conn:
        return _dict(
            conn.execute(
                """
                SELECT *
                FROM presentation_queue
                WHERE id = ?
                """,
                (int(queue_id),),
            ).fetchone()
        )


def counts_by_estado():
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT estado, COUNT(*) AS total
            FROM presentation_queue
            GROUP BY estado
            """
        ).fetchall()

    data = {row["estado"]: row["total"] for row in rows}

    return {
        "pendiente": data.get(QUEUE_PENDING, 0),
        "en_proceso": data.get(QUEUE_RUNNING, 0),
        "lanzado": data.get(QUEUE_LAUNCHED, 0),
        "completado": data.get(QUEUE_DONE, 0),
        "error": data.get(QUEUE_ERROR, 0),
        "cancelado": data.get(QUEUE_CANCELLED, 0),
        "total": sum(data.values()),
    }


def mark_cancelled(queue_id):
    item = get_queue_item(queue_id)
    now = _now()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE presentation_queue
            SET estado = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (QUEUE_CANCELLED, now, int(queue_id)),
        )
        conn.commit()

    if item:
        _register_trace(
            item["expediente_id"],
            "COLA_PRESENTACION",
            "ELEMENTO DE COLA CANCELADO",
            f"Se cancela el elemento de cola #{queue_id}.",
        )


def reset_to_pending(queue_id):
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE presentation_queue
            SET estado = ?,
                pid = NULL,
                last_error = NULL,
                updated_at = ?,
                started_at = NULL,
                finished_at = NULL
            WHERE id = ?
            """,
            (QUEUE_PENDING, now, int(queue_id)),
        )
        conn.commit()


def mark_presented(queue_id):
    item = get_queue_item(queue_id)
    if not item:
        raise ValueError("Elemento de cola no encontrado")

    if item.get("estado") not in (QUEUE_LAUNCHED, QUEUE_RUNNING, QUEUE_DONE):
        raise ValueError(f"No se puede marcar presentado un elemento en estado {item.get('estado')}")

    now = _now()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE presentation_queue
            SET estado = ?,
                updated_at = ?,
                finished_at = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (QUEUE_DONE, now, now, int(queue_id)),
        )
        conn.commit()

    _register_trace(
        item["expediente_id"],
        "PRESENTACION_ASISTIDA",
        "EXPEDIENTE MARCADO COMO PRESENTADO",
        f"El expediente se marca manualmente como presentado desde la cola de presentación. Cola #{queue_id}.",
    )

    return {
        "ok": True,
        "queue_id": int(queue_id),
        "message": "Expediente marcado como presentado",
    }



def mark_presented_by_expediente(expediente_id, source="justificante_presentacion"):
    """
    Marca como completada la última cola activa de un expediente.

    Criterio funcional:
    - No se marca presentado al lanzar Mercurio.
    - Se marca presentado cuando se anexa el justificante de presentación.
    """
    expediente_id = int(expediente_id)
    now = _now()

    with _connect() as conn:
        target = conn.execute(
            """
            SELECT id, estado
            FROM presentation_queue
            WHERE expediente_id = ?
              AND estado IN ('lanzado', 'en_proceso', 'pendiente', 'error')
            ORDER BY
                CASE estado
                    WHEN 'lanzado' THEN 0
                    WHEN 'en_proceso' THEN 1
                    WHEN 'pendiente' THEN 2
                    WHEN 'error' THEN 3
                    ELSE 4
                END,
                updated_at DESC,
                id DESC
            LIMIT 1
            """,
            (expediente_id,),
        ).fetchone()

        if not target:
            return {
                "ok": True,
                "changed": False,
                "message": "No hay cola activa que marcar como presentada",
            }

        # La tabla tiene UNIQUE(expediente_id, estado). Si ya existía un completado
        # histórico de este expediente, lo movemos a completado_anterior para poder
        # cerrar la cola activa sin romper la restricción.
        conn.execute(
            """
            UPDATE presentation_queue
            SET estado = ?,
                updated_at = ?
            WHERE expediente_id = ?
              AND estado = ?
              AND id <> ?
            """,
            ("completado_anterior", now, expediente_id, QUEUE_DONE, int(target["id"])),
        )

        conn.execute(
            """
            UPDATE presentation_queue
            SET estado = ?,
                updated_at = ?,
                finished_at = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (QUEUE_DONE, now, now, int(target["id"])),
        )

        conn.commit()

    _register_trace(
        expediente_id,
        "PRESENTACION_ASISTIDA",
        "EXPEDIENTE MARCADO COMO PRESENTADO",
        f"El expediente se marca como presentado al anexar justificante de presentación. Origen: {source}.",
    )

    return {
        "ok": True,
        "changed": True,
        "queue_id": int(target["id"]),
        "estado_anterior": target["estado"],
        "estado_nuevo": QUEUE_DONE,
        "message": "Cola marcada como presentada por justificante",
    }


def execute_queue_item(queue_id):
    item = get_queue_item(queue_id)
    if not item:
        raise ValueError("Elemento de cola no encontrado")

    if item.get("estado") not in (QUEUE_PENDING, QUEUE_ERROR):
        raise ValueError(f"No se puede ejecutar un elemento en estado {item.get('estado')}")

    expediente = get_expediente_for_queue(item["expediente_id"])
    if not expediente:
        raise ValueError("Expediente no encontrado")

    now = _now()

    with _connect() as conn:
        conn.execute(
            """
            UPDATE presentation_queue
            SET estado = ?,
                intentos = COALESCE(intentos, 0) + 1,
                started_at = ?,
                updated_at = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (QUEUE_RUNNING, now, now, int(queue_id)),
        )
        conn.commit()

    try:
        context = presentation_assistant_service.start_presentation_for_expediente(expediente)
        pid = context.get("pid")
        now = _now()

        with _connect() as conn:
            conn.execute(
                """
                UPDATE presentation_queue
                SET estado = ?,
                    pid = ?,
                    updated_at = ?,
                    finished_at = NULL
                WHERE id = ?
                """,
                (QUEUE_LAUNCHED, pid, now, int(queue_id)),
            )
            conn.commit()

        _register_trace(
            item["expediente_id"],
            "PRESENTACION_ASISTIDA",
            "PRESENTACION ASISTIDA LANZADA DESDE COLA",
            f"Se lanza la presentación asistida desde la cola. Cola #{queue_id}. PID: {pid or '-'}",
        )

        return {
            "ok": True,
            "pid": pid,
            "queue_id": int(queue_id),
            "message": "Presentación asistida lanzada",
            "context": context,
        }

    except Exception as exc:
        now = _now()
        with _connect() as conn:
            conn.execute(
                """
                UPDATE presentation_queue
                SET estado = ?,
                    last_error = ?,
                    updated_at = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (QUEUE_ERROR, str(exc), now, now, int(queue_id)),
            )
            conn.commit()

        _register_trace(
            item["expediente_id"],
            "PRESENTACION_ASISTIDA_ERROR",
            "ERROR AL LANZAR PRESENTACION DESDE COLA",
            f"Error en cola #{queue_id}: {str(exc)}",
        )

        raise
