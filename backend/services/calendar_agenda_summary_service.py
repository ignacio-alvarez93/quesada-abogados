"""
Resumen operativo de Agenda para canales externos.

Responsabilidades:
- consumir la proyección canónica de calendar_service;
- construir una fotografía operativa de tareas y avisos;
- generar un resumen legible;
- fragmentarlo si es demasiado largo;
- delegar el transporte a telegram_service.

No conoce Flet ni controles de interfaz.
"""

from datetime import datetime, timedelta

from backend.services import (
    calendar_service,
    telegram_service,
)


DEFAULT_MESSAGE_LIMIT = 3500

OPEN_TASK_STATES = {
    "PENDIENTE",
    "EN_CURSO",
}


def _text(value):
    return str(
        value or ""
    ).strip()


def _upper(value):
    return _text(value).upper()


def _parse_datetime(value):
    raw = _text(value)

    if not raw:
        return None

    try:
        return datetime.fromisoformat(
            raw.replace(
                "T",
                " ",
            )
        )
    except ValueError:
        return None


def _priority_rank(value):
    return {
        "URGENTE": 0,
        "ALTA": 1,
        "NORMAL": 2,
        "BAJA": 3,
    }.get(
        _upper(value),
        9,
    )


def _task_sort_key(item):
    parsed = _parse_datetime(
        item.get("date")
    )

    return (
        parsed or datetime.max,
        _priority_rank(
            item.get("priority")
        ),
        _text(
            item.get("title")
        ).upper(),
    )


def build_agenda_snapshot(
    *,
    now=None,
    items=None,
    conn=None,
    db_path=calendar_service.DEFAULT_DB_PATH,
):
    """
    Construye una fotografía operativa independiente
    de los filtros visuales de Agenda.
    """

    current = (
        now
        or datetime.now()
    ).replace(
        microsecond=0
    )

    if items is None:
        items = (
            calendar_service
            .list_calendar_items(
                conn=conn,
                db_path=db_path,
            )
        )

    all_items = list(
        items or []
    )

    open_tasks = [
        item
        for item in all_items
        if _upper(
            item.get("item_type")
        ) == "TASK"
        and _upper(
            item.get("status")
        ) in OPEN_TASK_STATES
    ]

    pending_tasks = [
        item
        for item in open_tasks
        if _upper(
            item.get("status")
        ) == "PENDIENTE"
    ]

    in_progress_tasks = [
        item
        for item in open_tasks
        if _upper(
            item.get("status")
        ) == "EN_CURSO"
    ]

    overdue_tasks = []
    today_tasks = []
    next_7_days_tasks = []

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

    end_7_days = (
        current
        + timedelta(days=7)
    )

    for item in open_tasks:
        due = _parse_datetime(
            item.get("date")
        )

        if due is None:
            continue

        if due < start_today:
            overdue_tasks.append(
                item
            )

        if (
            start_today
            <= due
            <= end_today
        ):
            today_tasks.append(
                item
            )

        if (
            current
            <= due
            <= end_7_days
        ):
            next_7_days_tasks.append(
                item
            )

    active_alerts = [
        item
        for item in all_items
        if _upper(
            item.get("item_type")
        ) == "ALERT"
        and _upper(
            item.get("status")
        ) == "ACTIVO"
    ]

    for collection in (
        open_tasks,
        pending_tasks,
        in_progress_tasks,
        overdue_tasks,
        today_tasks,
        next_7_days_tasks,
        active_alerts,
    ):
        collection.sort(
            key=_task_sort_key
        )

    return {
        "generated_at": current,
        "all_items": all_items,
        "open_tasks": open_tasks,
        "pending_tasks": pending_tasks,
        "in_progress_tasks":
            in_progress_tasks,
        "overdue_tasks": overdue_tasks,
        "today_tasks": today_tasks,
        "next_7_days_tasks":
            next_7_days_tasks,
        "active_alerts": active_alerts,
        "counts": {
            "open_tasks":
                len(open_tasks),
            "pending_tasks":
                len(pending_tasks),
            "in_progress_tasks":
                len(in_progress_tasks),
            "overdue_tasks":
                len(overdue_tasks),
            "today_tasks":
                len(today_tasks),
            "next_7_days_tasks":
                len(next_7_days_tasks),
            "active_alerts":
                len(active_alerts),
        },
    }


def _format_due(value):
    parsed = _parse_datetime(
        value
    )

    if parsed is None:
        return "Sin fecha"

    return parsed.strftime(
        "%d/%m/%Y · %H:%M"
    )


def _format_task(
    item,
    index,
):
    client = (
        _text(
            item.get("client_name")
        )
        or "Sin cliente"
    )

    expedient = (
        _text(
            item.get(
                "expedient_number"
            )
        )
        or "Sin expediente"
    )

    responsible = (
        _text(
            item.get("responsible")
        )
        or "Ignacio Alvarez"
    )

    title = (
        _text(
            item.get("title")
        )
        or "Sin título"
    )

    priority = (
        _upper(
            item.get("priority")
        )
        or "NORMAL"
    )

    return "\n".join(
        (
            f"{index}. {title}",
            f"👤 {client}",
            f"📁 {expedient}",
            (
                "📅 "
                f"{_format_due(item.get('date'))}"
            ),
            f"⚡ {priority}",
            f"👨‍💼 {responsible}",
        )
    )


def _task_section(
    title,
    items,
):
    if not items:
        return ""

    blocks = [
        title,
        "",
    ]

    for index, item in enumerate(
        items,
        start=1,
    ):
        blocks.append(
            _format_task(
                item,
                index,
            )
        )
        blocks.append("")

    return "\n".join(
        blocks
    ).rstrip()


def build_agenda_summary_message(
    snapshot,
):
    generated_at = snapshot[
        "generated_at"
    ]

    counts = snapshot[
        "counts"
    ]

    blocks = [
        "📅 QUESADA ABOGADOS · AGENDA",
        generated_at.strftime(
            "%d/%m/%Y · %H:%M"
        ),
        "",
        "📊 RESUMEN OPERATIVO",
        "",
        (
            "🔴 Vencidas: "
            f"{counts['overdue_tasks']}"
        ),
        (
            "📌 Pendientes: "
            f"{counts['pending_tasks']}"
        ),
        (
            "🟠 En curso: "
            f"{counts['in_progress_tasks']}"
        ),
        (
            "📅 Para hoy: "
            f"{counts['today_tasks']}"
        ),
        (
            "🗓 Próximos 7 días: "
            f"{counts['next_7_days_tasks']}"
        ),
        (
            "🔔 Avisos activos: "
            f"{counts['active_alerts']}"
        ),
    ]

    overdue_section = (
        _task_section(
            "🔴 TAREAS VENCIDAS",
            snapshot[
                "overdue_tasks"
            ],
        )
    )

    pending_non_overdue = [
        item
        for item in snapshot[
            "pending_tasks"
        ]
        if item not in snapshot[
            "overdue_tasks"
        ]
    ]

    pending_section = (
        _task_section(
            "📌 TAREAS PENDIENTES",
            pending_non_overdue,
        )
    )

    progress_non_overdue = [
        item
        for item in snapshot[
            "in_progress_tasks"
        ]
        if item not in snapshot[
            "overdue_tasks"
        ]
    ]

    progress_section = (
        _task_section(
            "🟠 EN CURSO",
            progress_non_overdue,
        )
    )

    for section in (
        overdue_section,
        pending_section,
        progress_section,
    ):
        if not section:
            continue

        blocks.extend(
            (
                "",
                "────────────────────",
                "",
                section,
            )
        )

    if not snapshot["open_tasks"]:
        blocks.extend(
            (
                "",
                "✅ No hay tareas abiertas.",
            )
        )

    blocks.extend(
        (
            "",
            (
                "Total de tareas abiertas: "
                f"{counts['open_tasks']}"
            ),
        )
    )

    return "\n".join(
        blocks
    ).strip()


def split_message(
    text,
    *,
    max_length=DEFAULT_MESSAGE_LIMIT,
):
    """
    Divide preferentemente por párrafos.

    El límite conservador evita acercarnos
    al máximo de Telegram.
    """

    clean = _text(text)

    if not clean:
        return []

    limit = max(
        int(max_length),
        100,
    )

    if len(clean) <= limit:
        return [
            clean
        ]

    paragraphs = clean.split(
        "\n\n"
    )

    chunks = []
    current = ""

    for paragraph in paragraphs:
        candidate = (
            paragraph
            if not current
            else (
                current
                + "\n\n"
                + paragraph
            )
        )

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(
                current
            )
            current = ""

        while len(paragraph) > limit:
            chunks.append(
                paragraph[:limit]
            )
            paragraph = (
                paragraph[limit:]
            )

        current = paragraph

    if current:
        chunks.append(
            current
        )

    return chunks


def send_agenda_summary(
    *,
    now=None,
    conn=None,
    db_path=calendar_service.DEFAULT_DB_PATH,
    token=None,
    chat_id=None,
    timeout=15,
    max_message_length=DEFAULT_MESSAGE_LIMIT,
):
    """
    Construye y envía el resumen operativo actual.

    Devuelve información suficiente para que la UI
    pueda confirmar el resultado sin conocer Telegram.
    """

    snapshot = build_agenda_snapshot(
        now=now,
        conn=conn,
        db_path=db_path,
    )

    message = (
        build_agenda_summary_message(
            snapshot
        )
    )

    messages = split_message(
        message,
        max_length=max_message_length,
    )

    sent = 0

    for part in messages:
        telegram_service.send_message(
            part,
            token=token,
            chat_id=chat_id,
            timeout=timeout,
        )

        sent += 1

    return {
        "sent": sent,
        "message_count":
            len(messages),
        "snapshot": snapshot,
        "messages": messages,
    }
