"""
Construcción de mensajes operativos.

Este módulo no envía nada.

Transforma el contexto de una notificación programada en
texto reutilizable por Telegram u otros canales futuros.
"""

from datetime import datetime


def _text(value):
    return str(value or "").strip()


def _format_datetime(value):
    raw = _text(value)

    if not raw:
        return "-"

    try:
        parsed = datetime.fromisoformat(
            raw.replace("T", " ")
        )
    except ValueError:
        return raw

    if (
        parsed.hour == 0
        and parsed.minute == 0
        and parsed.second == 0
    ):
        return parsed.strftime(
            "%d/%m/%Y"
        )

    return parsed.strftime(
        "%d/%m/%Y %H:%M"
    )


def _client_name(source):
    parts = [
        source.get("cliente_nombre"),
        source.get(
            "cliente_primer_apellido"
        ),
        source.get(
            "cliente_segundo_apellido"
        ),
    ]

    value = " ".join(
        _text(part)
        for part in parts
        if _text(part)
    )

    return value or "-"


def build_notification_message(
    notification,
):
    """
    Construye el texto final según source_type.

    Espera una notificación obtenida mediante
    scheduled_notification_service.list_due_notifications(),
    con delivery_context incluido.
    """

    if not notification:
        raise ValueError(
            "La notificación es obligatoria."
        )

    source_type = _text(
        notification.get("source_type")
    ).upper()

    context = (
        notification.get(
            "delivery_context"
        )
        or {}
    )

    source = (
        context.get("source")
        or {}
    )

    if source_type == "TASK":
        return _build_task_message(
            source
        )

    if source_type == "ALERT":
        return _build_alert_message(
            source
        )

    raise ValueError(
        "Tipo de origen no soportado."
    )


def _build_task_message(task):
    title = (
        _text(task.get("titulo"))
        or "Tarea"
    )

    lines = [
        "✅ TAREA · QUESADA ABOGADOS",
        "",
        title,
    ]

    description = _text(
        task.get("descripcion")
    )

    if description:
        lines.extend(
            [
                "",
                description,
            ]
        )

    lines.extend(
        [
            "",
            f"Cliente: {_client_name(task)}",
            (
                "Expediente: "
                f"{_text(task.get('numero_expediente')) or '-'}"
            ),
            (
                "Vence: "
                f"{_format_datetime(task.get('fecha_vencimiento'))}"
            ),
            (
                "Prioridad: "
                f"{_text(task.get('prioridad')) or 'NORMAL'}"
            ),
        ]
    )

    return "\n".join(lines)


def _build_alert_message(alert):
    title = (
        _text(alert.get("titulo"))
        or "Aviso"
    )

    lines = [
        "⚠️ AVISO · QUESADA ABOGADOS",
        "",
        title,
    ]

    description = _text(
        alert.get("descripcion")
    )

    if description:
        lines.extend(
            [
                "",
                description,
            ]
        )

    lines.extend(
        [
            "",
            f"Cliente: {_client_name(alert)}",
            (
                "Expediente: "
                f"{_text(alert.get('numero_expediente')) or '-'}"
            ),
            (
                "Fecha relevante: "
                f"{_format_datetime(alert.get('fecha_evento'))}"
            ),
            (
                "Prioridad: "
                f"{_text(alert.get('prioridad')) or 'NORMAL'}"
            ),
        ]
    )

    return "\n".join(lines)
