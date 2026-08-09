from datetime import datetime

import flet as ft

from frontend.components.app_card import (
    info_card,
)
from frontend.components.app_table import (
    app_table,
)
from frontend.components.listing.status_chip import (
    status_chip,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"


PRIORITY_STATUS_MAP = {
    "BAJA": (
        "Baja",
        "#ECFDF3",
        "#027A48",
    ),
    "NORMAL": (
        "Normal",
        "#F1F5F9",
        "#475569",
    ),
    "ALTA": (
        "Alta",
        "#FFF1F0",
        "#D92D20",
    ),
    "URGENTE": (
        "Urgente",
        "#FEF3F2",
        "#B42318",
    ),
}


ITEM_STATUS_MAP = {
    "PENDIENTE": (
        "Pendiente",
        "#FFF7E6",
        "#B54708",
    ),
    "EN_CURSO": (
        "En curso",
        "#EEF6FF",
        "#0057B8",
    ),
    "COMPLETADA": (
        "Completada",
        "#ECFDF3",
        "#027A48",
    ),
    "CANCELADA": (
        "Cancelada",
        "#F1F5F9",
        "#475569",
    ),
    "ACTIVO": (
        "Activo",
        "#FFF7E6",
        "#B54708",
    ),
    "RESUELTO": (
        "Resuelto",
        "#ECFDF3",
        "#027A48",
    ),
    "CANCELADO": (
        "Cancelado",
        "#F1F5F9",
        "#475569",
    ),
}


DAY_NAMES = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]


MONTH_NAMES = [
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def _parse_datetime(
    value,
):
    try:
        return datetime.fromisoformat(
            str(value or "").replace(
                "T",
                " ",
            )
        )
    except Exception:
        return None


def _time_label(
    value,
):
    parsed = _parse_datetime(
        value
    )

    if not parsed:
        return "-"

    return parsed.strftime(
        "%H:%M"
    )


def _date_title(
    day,
):
    return (
        f"{DAY_NAMES[day.weekday()]} "
        f"{day.day:02d}/"
        f"{day.month:02d}/"
        f"{day.year}"
    )


def _long_date(
    day,
):
    return (
        f"{DAY_NAMES[day.weekday()]}, "
        f"{day.day:02d} de "
        f"{MONTH_NAMES[day.month]} "
        f"de {day.year}"
    )


def _relation_label(
    item,
):
    client = str(
        item.get(
            "client_name"
        )
        or ""
    ).strip()

    expedient = str(
        item.get(
            "expedient_number"
        )
        or ""
    ).strip()

    if client and expedient:
        return (
            f"{client} · {expedient}"
        )

    return (
        client
        or expedient
        or "-"
    )


def _item_title_control(
    item,
):
    item_type = str(
        item.get(
            "item_type"
        )
        or "TASK"
    ).upper()

    dot_color = (
        "#B54708"
        if item_type == "ALERT"
        else Q_PRIMARY
    )

    return ft.Row(
        controls=[
            ft.Text(
                "●",
                size=9,
                color=dot_color,
            ),
            ft.Column(
                controls=[
                    ft.Text(
                        str(
                            item.get(
                                "title"
                            )
                            or "-"
                        ),
                        size=11,
                        weight=(
                            ft.FontWeight.W_600
                        ),
                        color=(
                            Q_PRIMARY_DARK
                        ),
                        max_lines=1,
                        overflow=(
                            ft.TextOverflow
                            .ELLIPSIS
                        ),
                    ),
                    ft.Text(
                        (
                            "Aviso"
                            if item_type
                            == "ALERT"
                            else "Tarea"
                        ),
                        size=9,
                        color=Q_MUTED,
                    ),
                ],
                spacing=1,
            ),
        ],
        spacing=6,
    )


def _rows(
    items,
    on_item_click=None,
):
    rows = []

    for item in items:
        item_type = str(
            item.get(
                "item_type"
            )
            or "TASK"
        ).upper()

        status = str(
            item.get(
                "status"
            )
            or "-"
        ).upper()

        priority = str(
            item.get(
                "priority"
            )
            or "NORMAL"
        ).upper()

        if (
            item_type == "ALERT"
            and status == "ACTIVO"
        ):
            status_control = (
                status_chip(
                    "ACTIVO",
                    label="Aviso",
                    status_map={
                        "ACTIVO": (
                            "Aviso",
                            "#FFF7E6",
                            "#B54708",
                        ),
                    },
                )
            )
        else:
            status_control = (
                status_chip(
                    status,
                    status_map=(
                        ITEM_STATUS_MAP
                    ),
                )
            )

        rows.append(
            [
                {
                    "on_click": (
                        None
                        if on_item_click
                        is None
                        else lambda e,
                        current=item:
                            on_item_click(
                                current
                            )
                    ),
                },
                _time_label(
                    item.get(
                        "date"
                    )
                ),
                _item_title_control(
                    item
                ),
                _relation_label(
                    item
                ),
                status_chip(
                    priority,
                    status_map=(
                        PRIORITY_STATUS_MAP
                    ),
                ),
                status_control,
            ]
        )

    return rows


TODAY_HEADERS = [
    {
        "key": "Hora",
        "label": "Hora",
        "width": 90,
    },
    {
        "key": "Tarea",
        "label": "Tarea / Aviso",
        "width": 280,
    },
    {
        "key": "Cliente",
        "label": (
            "Cliente / Expediente"
        ),
        "width": 330,
    },
    {
        "key": "Prioridad",
        "label": "Prioridad",
        "width": 130,
    },
    {
        "key": "Estado",
        "label": "Estado",
        "width": 145,
    },
]


def _metric_box(
    value,
    label,
    icon,
    icon_color,
):
    return ft.Container(
        expand=True,
        height=84,
        bgcolor="#FFFFFF",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=12,
        padding=12,
        content=ft.Row(
            controls=[
                ft.Icon(
                    icon,
                    size=26,
                    color=icon_color,
                ),
                ft.Column(
                    controls=[
                        ft.Text(
                            str(value),
                            size=20,
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color=(
                                Q_PRIMARY_DARK
                            ),
                        ),
                        ft.Text(
                            label,
                            size=10,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=1,
                ),
            ],
            spacing=10,
            vertical_alignment=(
                ft.CrossAxisAlignment
                .CENTER
            ),
        ),
    )


def _today_metrics(
    items,
):
    total = len(items)

    in_progress = sum(
        1
        for item in items
        if str(
            item.get("status")
            or ""
        ).upper()
        == "EN_CURSO"
    )

    alerts = sum(
        1
        for item in items
        if str(
            item.get(
                "item_type"
            )
            or ""
        ).upper()
        == "ALERT"
    )

    high_priority = sum(
        1
        for item in items
        if str(
            item.get(
                "priority"
            )
            or ""
        ).upper()
        in {
            "ALTA",
            "URGENTE",
        }
    )

    return ft.Row(
        controls=[
            _metric_box(
                total,
                "Actuaciones hoy",
                ft.Icons
                .ASSIGNMENT_TURNED_IN_OUTLINED,
                Q_PRIMARY,
            ),
            _metric_box(
                in_progress,
                "En curso",
                ft.Icons
                .CHECK_CIRCLE_OUTLINE,
                "#2E90FA",
            ),
            _metric_box(
                alerts,
                "Avisos",
                ft.Icons
                .SCHEDULE_OUTLINED,
                "#F79009",
            ),
            _metric_box(
                high_priority,
                "Alta prioridad",
                ft.Icons
                .ERROR_OUTLINE,
                "#D92D20",
            ),
        ],
        spacing=10,
    )


def calendar_today_primary(
    items,
    day,
    on_item_click=None,
):
    table = app_table(
        headers=TODAY_HEADERS,
        rows=_rows(
            items,
            on_item_click=(
                on_item_click
            ),
        ),
        height=300,
    )

    if not items:
        table = ft.Container(
            height=300,
            alignment=ft.Alignment(
                0,
                0,
            ),
            content=ft.Column(
                controls=[
                    ft.Icon(
                        ft.Icons
                        .EVENT_AVAILABLE_OUTLINED,
                        size=32,
                        color="#98A2B3",
                    ),
                    ft.Text(
                        (
                            "No hay actuaciones "
                            "para hoy."
                        ),
                        size=12,
                        color=Q_MUTED,
                    ),
                ],
                spacing=8,
                horizontal_alignment=(
                    ft.CrossAxisAlignment
                    .CENTER
                ),
            ),
        )

    card = info_card(
        (
            "Hoy · "
            + _date_title(
                day
            )
        ),
        ft.Column(
            controls=[
                table,
            ],
            spacing=8,
        ),
    )

    return ft.Row(
        controls=[
            ft.Container(
                content=card,
                expand=True,
            ),
        ],
        spacing=0,
    )


def calendar_today_summary(
    items,
    day,
    on_item_click=None,
):
    compact_table = app_table(
        headers=TODAY_HEADERS,
        rows=_rows(
            items,
            on_item_click=(
                on_item_click
            ),
        ),
        height=190,
    )

    content = ft.Column(
        controls=[
            ft.Text(
                _long_date(
                    day
                ),
                size=10,
                color=Q_MUTED,
            ),
            _today_metrics(
                items
            ),
            (
                compact_table
                if items
                else ft.Container(
                    height=110,
                    alignment=(
                        ft.Alignment(
                            0,
                            0,
                        )
                    ),
                    content=ft.Text(
                        (
                            "Sin actuaciones "
                            "registradas para hoy."
                        ),
                        size=11,
                        color=Q_MUTED,
                    ),
                )
            ),
        ],
        spacing=10,
    )

    return info_card(
        "Resumen del día",
        content,
    )
