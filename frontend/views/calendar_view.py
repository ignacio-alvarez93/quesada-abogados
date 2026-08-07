from datetime import datetime, timedelta

import flet as ft

from backend.services import calendar_service

from frontend.components.app_button import (
    primary_button,
    secondary_button,
)

from frontend.components.app_card import (
    metric_card,
)

from frontend.components.app_dropdown import (
    select_input,
)

from frontend.components.app_text_field import (
    text_input,
)

from frontend.components.listing.status_chip import (
    status_chip,
)

from frontend.components.calendar import (
    calendar_week_grid,
    calendar_summary_panel,
)


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"
Q_BG = "#F5F8FC"


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
        "#EEF4FF",
        "#0057B8",
    ),
    "URGENTE": (
        "Urgente",
        "#FEF3F2",
        "#B42318",
    ),
}


def _monday(value):
    current = (
        value
        if isinstance(value, datetime)
        else datetime.now()
    )

    return (
        current
        - timedelta(
            days=current.weekday()
        )
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _date_display(value):
    raw = str(value or "")

    try:
        parsed = datetime.fromisoformat(
            raw.replace(
                "T",
                " ",
            )
        )

        return parsed.strftime(
            "%d/%m/%Y %H:%M"
        )

    except Exception:
        return raw


def calendar_view(
    page: ft.Page,
    on_open_expediente=None,
    on_open_cliente=None,
):
    state = {
        "week_start": _monday(
            datetime.now()
        ),
        "items": [],
        "summary": {},
        "selected_item": None,
    }

    content = ft.Container(
        expand=True,
    )

    search_input = text_input(
        "Buscar tarea / aviso / expediente / cliente",
        width=360,
    )

    responsible_filter = (
        select_input(
            "Responsable",
            ["Todos"],
            value="Todos",
            width=190,
        )
    )

    priority_filter = select_input(
        "Prioridad",
        [
            "Todos",
            "BAJA",
            "NORMAL",
            "ALTA",
            "URGENTE",
        ],
        value="Todos",
        width=170,
    )

    status_filter = select_input(
        "Estado",
        [
            "Todos",
            "PENDIENTE",
            "EN_CURSO",
            "COMPLETADA",
            "ACTIVO",
            "RESUELTO",
        ],
        value="Todos",
        width=180,
    )

    type_filter = select_input(
        "Tipo",
        [
            "Todos",
            "TASK",
            "ALERT",
        ],
        value="Todos",
        width=160,
    )

    def safe_update():
        try:
            content.update()
        except Exception:
            pass

    def show_placeholder(
        message,
    ):
        page.snack_bar = ft.SnackBar(
            ft.Text(message)
        )
        page.snack_bar.open = True
        page.update()

    def previous_week(e=None):
        state["week_start"] -= (
            timedelta(days=7)
        )

        refresh()

    def next_week(e=None):
        state["week_start"] += (
            timedelta(days=7)
        )

        refresh()

    def current_week(e=None):
        state["week_start"] = (
            _monday(
                datetime.now()
            )
        )

        refresh()

    def select_item(item):
        state["selected_item"] = item
        render()
        safe_update()

    def open_selected_expedient(
        e=None,
    ):
        item = state.get(
            "selected_item"
        ) or {}

        expedient_id = item.get(
            "expediente_id"
        )

        if (
            expedient_id
            and on_open_expediente
        ):
            on_open_expediente(
                expedient_id
            )

    def filtered_items():
        search = (
            search_input.value
            or ""
        ).strip().upper()

        priority = (
            priority_filter.value
            or "Todos"
        )

        status = (
            status_filter.value
            or "Todos"
        )

        item_type = (
            type_filter.value
            or "Todos"
        )

        responsible = (
            responsible_filter.value
            or "Todos"
        )

        result = []

        for item in state["items"]:
            if (
                priority != "Todos"
                and item.get("priority")
                != priority
            ):
                continue

            if (
                status != "Todos"
                and item.get("status")
                != status
            ):
                continue

            if (
                item_type != "Todos"
                and item.get(
                    "item_type"
                )
                != item_type
            ):
                continue

            if (
                responsible != "Todos"
                and item.get(
                    "responsible"
                )
                != responsible
            ):
                continue

            if search:
                haystack = " ".join(
                    [
                        str(
                            item.get("title")
                            or ""
                        ),
                        str(
                            item.get(
                                "description"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "client_name"
                            )
                            or ""
                        ),
                        str(
                            item.get(
                                "expedient_number"
                            )
                            or ""
                        ),
                    ]
                ).upper()

                if search not in haystack:
                    continue

            result.append(item)

        return result

    def upcoming_table(items):
        rows = []

        for item in items[:8]:
            item_type = item.get(
                "item_type"
            )

            rows.append(
                ft.Container(
                    padding=ft.padding.symmetric(
                        horizontal=10,
                        vertical=8,
                    ),
                    border=ft.border.only(
                        bottom=ft.BorderSide(
                            1,
                            Q_BORDER,
                        )
                    ),
                    ink=True,
                    on_click=(
                        lambda e,
                        current=item:
                            select_item(
                                current
                            )
                    ),
                    content=ft.Row(
                        controls=[
                            ft.Text(
                                "●",
                                size=10,
                                color=(
                                    "#B54708"
                                    if item_type
                                    == "ALERT"
                                    else Q_PRIMARY
                                ),
                            ),
                            ft.Container(
                                width=250,
                                content=ft.Column(
                                    controls=[
                                        ft.Text(
                                            item.get(
                                                "title"
                                            )
                                            or "-",
                                            size=11,
                                            weight=(
                                                ft.FontWeight
                                                .W_600
                                            ),
                                            color=(
                                                Q_PRIMARY_DARK
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
                            ),
                            ft.Container(
                                width=260,
                                content=ft.Text(
                                    (
                                        item.get(
                                            "client_name"
                                        )
                                        or item.get(
                                            "expedient_number"
                                        )
                                        or "-"
                                    ),
                                    size=10,
                                    color="#334155",
                                    overflow=(
                                        ft.TextOverflow
                                        .ELLIPSIS
                                    ),
                                ),
                            ),
                            ft.Container(
                                width=150,
                                content=ft.Text(
                                    _date_display(
                                        item.get(
                                            "date"
                                        )
                                    ),
                                    size=10,
                                    color="#334155",
                                ),
                            ),
                            ft.Container(
                                width=100,
                                content=status_chip(
                                    item.get(
                                        "priority"
                                    ),
                                    status_map=(
                                        PRIORITY_STATUS_MAP
                                    ),
                                ),
                            ),
                            ft.Container(
                                width=130,
                                content=ft.Text(
                                    item.get(
                                        "status"
                                    )
                                    or "-",
                                    size=10,
                                    color="#334155",
                                ),
                            ),
                            ft.Container(
                                width=130,
                                content=ft.Text(
                                    item.get(
                                        "responsible"
                                    )
                                    or "-",
                                    size=10,
                                    color="#334155",
                                ),
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=(
                            ft.CrossAxisAlignment
                            .CENTER
                        ),
                    ),
                )
            )

        if not rows:
            rows.append(
                ft.Container(
                    padding=24,
                    alignment=ft.Alignment(
                        0,
                        0,
                    ),
                    content=ft.Column(
                        controls=[
                            ft.Icon(
                                ft.Icons
                                .EVENT_AVAILABLE,
                                size=34,
                                color="#94A3B8",
                            ),
                            ft.Text(
                                "Sin actuaciones programadas",
                                size=13,
                                weight=(
                                    ft.FontWeight
                                    .W_600
                                ),
                                color=Q_MUTED,
                            ),
                            ft.Text(
                                (
                                    "Las nuevas tareas y avisos "
                                    "aparecerán aquí."
                                ),
                                size=11,
                                color="#94A3B8",
                            ),
                        ],
                        spacing=5,
                        horizontal_alignment=(
                            ft.CrossAxisAlignment
                            .CENTER
                        ),
                    ),
                )
            )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=ft.padding.only(
                left=14,
                right=14,
                top=12,
                bottom=10,
            ),
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Próximas actuaciones",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(
                                "Tarea / Aviso",
                                size=10,
                                color=Q_MUTED,
                                width=270,
                            ),
                            ft.Text(
                                "Cliente / Expediente",
                                size=10,
                                color=Q_MUTED,
                                width=260,
                            ),
                            ft.Text(
                                "Vencimiento",
                                size=10,
                                color=Q_MUTED,
                                width=150,
                            ),
                            ft.Text(
                                "Prioridad",
                                size=10,
                                color=Q_MUTED,
                                width=100,
                            ),
                            ft.Text(
                                "Estado",
                                size=10,
                                color=Q_MUTED,
                                width=130,
                            ),
                            ft.Text(
                                "Responsable",
                                size=10,
                                color=Q_MUTED,
                                width=130,
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Column(
                        controls=rows,
                        spacing=0,
                    ),
                ],
                spacing=8,
            ),
        )

    def detail_panel():
        item = state.get(
            "selected_item"
        )

        if not item:
            return ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(
                    1,
                    Q_BORDER,
                ),
                border_radius=14,
                padding=18,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "Detalle del elemento",
                            size=14,
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            (
                                "Selecciona una tarea o "
                                "aviso para ver su detalle."
                            ),
                            size=11,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=8,
                ),
            )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=18,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Detalle del elemento",
                        size=14,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Text(
                        item.get("title")
                        or "-",
                        size=13,
                        weight=(
                            ft.FontWeight.BOLD
                        ),
                        color=Q_PRIMARY_DARK,
                    ),
                    status_chip(
                        item.get(
                            "priority"
                        ),
                        status_map=(
                            PRIORITY_STATUS_MAP
                        ),
                    ),
                    ft.Divider(
                        color=Q_BORDER,
                    ),
                    ft.Text(
                        (
                            "Cliente: "
                            + (
                                item.get(
                                    "client_name"
                                )
                                or "-"
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    ft.Text(
                        (
                            "Expediente: "
                            + (
                                item.get(
                                    "expedient_number"
                                )
                                or "-"
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    ft.Text(
                        (
                            "Fecha: "
                            + _date_display(
                                item.get("date")
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    ft.Text(
                        (
                            "Estado: "
                            + (
                                item.get(
                                    "status"
                                )
                                or "-"
                            )
                        ),
                        size=11,
                        color="#334155",
                    ),
                    (
                        secondary_button(
                            "Abrir expediente",
                            open_selected_expedient,
                        )
                        if item.get(
                            "expediente_id"
                        )
                        else ft.Container()
                    ),
                ],
                spacing=8,
            ),
        )

    def render():
        week_start = state[
            "week_start"
        ]

        week_end = (
            week_start
            + timedelta(days=6)
        )

        items = filtered_items()

        header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "Calendario",
                            size=28,
                            weight=(
                                ft.FontWeight.BOLD
                            ),
                            color=Q_PRIMARY_DARK,
                        ),
                        ft.Text(
                            (
                                "Gestión operativa de tareas, "
                                "avisos y vencimientos del despacho"
                            ),
                            size=13,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
                secondary_button(
                    "Nuevo aviso",
                    lambda e:
                        show_placeholder(
                            "Formulario de aviso: siguiente fase."
                        ),
                ),
                primary_button(
                    "Nueva tarea",
                    lambda e:
                        show_placeholder(
                            "Formulario de tarea: siguiente fase."
                        ),
                ),
            ],
            vertical_alignment=(
                ft.CrossAxisAlignment.START
            ),
        )

        metrics = ft.Row(
            controls=[
                metric_card(
                    "Tareas pendientes",
                    state["summary"].get(
                        "pending_tasks",
                        0,
                    ),
                ),
                metric_card(
                    "Vencen hoy",
                    state["summary"].get(
                        "due_today",
                        0,
                    ),
                ),
                metric_card(
                    "Próximos 7 días",
                    state["summary"].get(
                        "next_7_days",
                        0,
                    ),
                ),
                metric_card(
                    "Avisos críticos",
                    state["summary"].get(
                        "critical_alerts",
                        0,
                    ),
                ),
            ],
            spacing=12,
            wrap=True,
        )

        controls_bar = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            border_radius=14,
            padding=10,
            content=ft.Row(
                controls=[
                    secondary_button(
                        "Hoy",
                        current_week,
                    ),
                    primary_button(
                        "Semana",
                        lambda e: None,
                    ),
                    secondary_button(
                        "Mes",
                        lambda e:
                            show_placeholder(
                                "Vista mensual: siguiente iteración visual."
                            ),
                    ),
                    search_input,
                    responsible_filter,
                    priority_filter,
                    status_filter,
                    type_filter,
                ],
                spacing=10,
                wrap=True,
            ),
        )

        calendar_header = ft.Row(
            controls=[
                secondary_button(
                    "‹",
                    previous_week,
                ),
                secondary_button(
                    "›",
                    next_week,
                ),
                ft.Text(
                    (
                        f"{week_start.strftime('%d/%m')}"
                        " – "
                        f"{week_end.strftime('%d/%m/%Y')}"
                    ),
                    size=14,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
            ],
            spacing=8,
        )

        left = ft.Column(
            controls=[
                calendar_header,
                calendar_week_grid(
                    items,
                    week_start,
                    on_item_click=(
                        select_item
                    ),
                ),
                upcoming_table(
                    calendar_service
                    .get_upcoming_items(
                        days=7,
                        limit=8,
                    )
                ),
            ],
            spacing=12,
            expand=True,
        )

        right = ft.Container(
            width=330,
            content=ft.Column(
                controls=[
                    calendar_summary_panel(
                        state["summary"],
                        calendar_service
                        .get_upcoming_items(
                            days=7,
                            limit=5,
                        ),
                    ),
                    detail_panel(),
                ],
                spacing=12,
            ),
        )

        content.content = ft.Container(
            expand=True,
            bgcolor=Q_BG,
            padding=18,
            content=ft.Column(
                controls=[
                    header,
                    metrics,
                    controls_bar,
                    ft.Row(
                        controls=[
                            left,
                            right,
                        ],
                        spacing=14,
                        vertical_alignment=(
                            ft.CrossAxisAlignment
                            .START
                        ),
                        expand=True,
                    ),
                ],
                spacing=14,
            ),
        )

    def refresh(e=None):
        week_start = state[
            "week_start"
        ]

        week_end = (
            week_start
            + timedelta(
                days=6,
                hours=23,
                minutes=59,
                seconds=59,
            )
        )

        state["items"] = (
            calendar_service
            .list_calendar_items(
                start_at=(
                    week_start.isoformat(
                        sep=" "
                    )
                ),
                end_at=(
                    week_end.isoformat(
                        sep=" "
                    )
                ),
            )
        )

        state["summary"] = (
            calendar_service
            .get_calendar_summary()
        )

        responsibles = sorted(
            {
                item.get(
                    "responsible"
                )
                for item
                in state["items"]
                if item.get(
                    "responsible"
                )
            }
        )

        current = (
            responsible_filter.value
            or "Todos"
        )

        responsible_filter.options = [
            ft.dropdown.Option(
                "Todos"
            ),
            *[
                ft.dropdown.Option(
                    value
                )
                for value
                in responsibles
            ],
        ]

        responsible_filter.value = (
            current
            if current
            in (
                ["Todos"]
                + responsibles
            )
            else "Todos"
        )

        render()
        safe_update()

    def filters_changed(e=None):
        render()
        safe_update()

    search_input.on_change = (
        filters_changed
    )

    responsible_filter.on_change = (
        filters_changed
    )

    priority_filter.on_change = (
        filters_changed
    )

    status_filter.on_change = (
        filters_changed
    )

    type_filter.on_change = (
        filters_changed
    )

    refresh()

    return content
