"""
Proyección operativa unificada del calendario.

Este servicio normaliza:

    tasks
    calendar_alerts

para que la interfaz no conozca la estructura interna
de ninguno de los dos dominios.

La UI consume únicamente CALENDAR ITEMS.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "quesada.db"
)


ITEM_TASK = "TASK"
ITEM_ALERT = "ALERT"


def _connect(db_path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(
        str(db_path),
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    return conn


@contextmanager
def _connection(
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    owns_connection = conn is None

    connection = (
        conn
        if conn is not None
        else _connect(db_path)
    )

    try:
        yield connection
    finally:
        if owns_connection:
            connection.close()


def _text(value):
    return str(value or "").strip()


def _upper(value):
    return _text(value).upper()


def _normalize_datetime(value):
    raw = _text(value)

    if not raw:
        return None

    try:
        return datetime.fromisoformat(
            raw.replace("T", " ")
        )
    except ValueError:
        return None


def _client_name(row):
    return " ".join(
        value
        for value in (
            _text(row["cliente_nombre"]),
            _text(row["cliente_primer_apellido"]),
            _text(row["cliente_segundo_apellido"]),
        )
        if value
    )


def _task_to_item(row):
    return {
        "item_type": ITEM_TASK,
        "source_id": int(row["id"]),
        "title": _text(row["titulo"]),
        "description": _text(row["descripcion"]),
        "date": _text(row["fecha_vencimiento"]),
        "warning_date": None,
        "priority": _upper(row["prioridad"]) or "NORMAL",
        "status": _upper(row["estado"]) or "PENDIENTE",
        "responsible": _text(row["responsable"]),
        "cliente_id": row["cliente_id"],
        "client_name": _client_name(row),
        "expediente_id": row["expediente_id"],
        "expedient_number": _text(row["numero_expediente"]),
        "origin_type": _upper(row["origen_tipo"]),
        "origin_id": row["origen_id"],
        "source_key": _text(row["source_key"]),
    }


def _alert_to_item(row):
    return {
        "item_type": ITEM_ALERT,
        "source_id": int(row["id"]),
        "title": _text(row["titulo"]),
        "description": _text(row["descripcion"]),
        "date": _text(row["fecha_evento"]),
        "warning_date": _text(row["fecha_inicio_aviso"]),
        "priority": _upper(row["prioridad"]) or "NORMAL",
        "status": _upper(row["estado"]) or "ACTIVO",
        "responsible": "",
        "cliente_id": row["cliente_id"],
        "client_name": _client_name(row),
        "expediente_id": row["expediente_id"],
        "expedient_number": _text(row["numero_expediente"]),
        "origin_type": _upper(row["origen_tipo"]),
        "origin_id": row["origen_id"],
        "source_key": _text(row["source_key"]),
    }


def _load_tasks(
    connection,
    start_at=None,
    end_at=None,
):
    sql = """
        SELECT
            t.*,

            c.nombre AS cliente_nombre,
            c.primer_apellido
                AS cliente_primer_apellido,
            c.segundo_apellido
                AS cliente_segundo_apellido,

            e.numero_expediente
                AS numero_expediente

        FROM tasks t

        LEFT JOIN clientes c
            ON c.id = t.cliente_id

        LEFT JOIN expedientes e
            ON e.id = t.expediente_id

        WHERE t.activo = 1
          AND t.estado NOT IN (
                'CANCELADA'
          )
    """

    params = []

    if start_at:
        sql += """
          AND datetime(
                t.fecha_vencimiento
              ) >= datetime(?)
        """
        params.append(start_at)

    if end_at:
        sql += """
          AND datetime(
                t.fecha_vencimiento
              ) <= datetime(?)
        """
        params.append(end_at)

    return [
        _task_to_item(row)
        for row in connection.execute(
            sql,
            params,
        ).fetchall()
    ]


def _load_alerts(
    connection,
    start_at=None,
    end_at=None,
):
    sql = """
        SELECT
            a.*,

            c.nombre AS cliente_nombre,
            c.primer_apellido
                AS cliente_primer_apellido,
            c.segundo_apellido
                AS cliente_segundo_apellido,

            e.numero_expediente
                AS numero_expediente

        FROM calendar_alerts a

        LEFT JOIN clientes c
            ON c.id = a.cliente_id

        LEFT JOIN expedientes e
            ON e.id = a.expediente_id

        WHERE a.activo = 1
          AND a.estado NOT IN (
                'CANCELADO'
          )
    """

    params = []

    if start_at:
        sql += """
          AND datetime(
                a.fecha_evento
              ) >= datetime(?)
        """
        params.append(start_at)

    if end_at:
        sql += """
          AND datetime(
                a.fecha_evento
              ) <= datetime(?)
        """
        params.append(end_at)

    return [
        _alert_to_item(row)
        for row in connection.execute(
            sql,
            params,
        ).fetchall()
    ]


def _matches_filters(
    item,
    *,
    item_type=None,
    priority=None,
    status=None,
    responsible=None,
    search=None,
):
    if item_type:
        if (
            _upper(item["item_type"])
            != _upper(item_type)
        ):
            return False

    if priority:
        if (
            _upper(item["priority"])
            != _upper(priority)
        ):
            return False

    if status:
        if (
            _upper(item["status"])
            != _upper(status)
        ):
            return False

    if responsible:
        if (
            _upper(responsible)
            not in _upper(item["responsible"])
        ):
            return False

    if search:
        haystack = " ".join(
            (
                item.get("title") or "",
                item.get("description") or "",
                item.get("client_name") or "",
                item.get("expedient_number") or "",
            )
        ).upper()

        if _upper(search) not in haystack:
            return False

    return True


def list_calendar_items(
    *,
    start_at=None,
    end_at=None,
    item_type=None,
    priority=None,
    status=None,
    responsible=None,
    search=None,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    Devuelve TASK + ALERT como colección homogénea.
    """

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        items = []

        if not item_type or _upper(
            item_type
        ) == ITEM_TASK:
            items.extend(
                _load_tasks(
                    connection,
                    start_at=start_at,
                    end_at=end_at,
                )
            )

        if not item_type or _upper(
            item_type
        ) == ITEM_ALERT:
            items.extend(
                _load_alerts(
                    connection,
                    start_at=start_at,
                    end_at=end_at,
                )
            )

    items = [
        item
        for item in items
        if _matches_filters(
            item,
            item_type=item_type,
            priority=priority,
            status=status,
            responsible=responsible,
            search=search,
        )
    ]

    items.sort(
        key=lambda item: (
            _normalize_datetime(
                item.get("date")
            )
            or datetime.max,
            item.get("item_type") or "",
            int(item.get("source_id") or 0),
        )
    )

    return items


def get_upcoming_items(
    *,
    now=None,
    days=7,
    limit=20,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    current = (
        now
        or datetime.now()
    ).replace(
        microsecond=0
    )

    end = (
        current
        + timedelta(days=int(days))
    )

    items = list_calendar_items(
        start_at=current.isoformat(
            sep=" "
        ),
        end_at=end.isoformat(
            sep=" "
        ),
        conn=conn,
        db_path=db_path,
    )

    return items[: int(limit)]


def get_calendar_summary(
    *,
    now=None,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    """
    KPIs principales de la pantalla Calendario.
    """

    current = (
        now
        or datetime.now()
    ).replace(
        microsecond=0
    )

    start_today = current.replace(
        hour=0,
        minute=0,
        second=0,
    )

    end_today = current.replace(
        hour=23,
        minute=59,
        second=59,
    )

    end_week = (
        current
        + timedelta(days=7)
    )

    with _connection(
        conn=conn,
        db_path=db_path,
    ) as connection:

        all_items = list_calendar_items(
            conn=connection,
            db_path=db_path,
        )

        today_items = list_calendar_items(
            start_at=start_today.isoformat(
                sep=" "
            ),
            end_at=end_today.isoformat(
                sep=" "
            ),
            conn=connection,
            db_path=db_path,
        )

        upcoming = list_calendar_items(
            start_at=current.isoformat(
                sep=" "
            ),
            end_at=end_week.isoformat(
                sep=" "
            ),
            conn=connection,
            db_path=db_path,
        )

        pending_telegram = (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM scheduled_notifications
                WHERE activo = 1
                  AND estado IN (
                        'PENDIENTE',
                        'ERROR'
                  )
                """
            ).fetchone()[0]
        )

    active_tasks = sum(
        1
        for item in all_items
        if item["item_type"] == ITEM_TASK
        and item["status"] in {
            "PENDIENTE",
            "EN_CURSO",
        }
    )

    critical_alerts = sum(
        1
        for item in all_items
        if item["item_type"] == ITEM_ALERT
        and item["status"] == "ACTIVO"
        and item["priority"] in {
            "ALTA",
            "URGENTE",
        }
    )

    return {
        "pending_tasks": active_tasks,
        "due_today": len(today_items),
        "next_7_days": len(upcoming),
        "critical_alerts": critical_alerts,
        "pending_telegram": int(
            pending_telegram
        ),
    }


def get_day_summary(
    day,
    *,
    conn=None,
    db_path=DEFAULT_DB_PATH,
):
    if isinstance(day, datetime):
        target = day
    else:
        target = datetime.fromisoformat(
            str(day)
        )

    start = target.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    end = target.replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=0,
    )

    items = list_calendar_items(
        start_at=start.isoformat(
            sep=" "
        ),
        end_at=end.isoformat(
            sep=" "
        ),
        conn=conn,
        db_path=db_path,
    )

    return {
        "date": start.date().isoformat(),
        "items": items,
        "tasks": sum(
            1
            for item in items
            if item["item_type"]
            == ITEM_TASK
        ),
        "alerts": sum(
            1
            for item in items
            if item["item_type"]
            == ITEM_ALERT
        ),
        "critical": sum(
            1
            for item in items
            if item["priority"]
            in {"ALTA", "URGENTE"}
        ),
    }
