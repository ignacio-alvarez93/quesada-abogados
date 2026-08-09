from datetime import datetime, timedelta

import flet as ft


Q_BORDER = "#E4E7EC"
Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"

DAY_NAMES = [
    "Lun",
    "Mar",
    "Mié",
    "Jue",
    "Vie",
    "Sáb",
    "Dom",
]


def _parse_date(value):
    try:
        return datetime.fromisoformat(
            str(value or "").replace(
                "T",
                " ",
            )
        )
    except Exception:
        return None


def _month_grid_start(
    month_anchor,
):
    first_day = month_anchor.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    return (
        first_day
        - timedelta(
            days=first_day.weekday()
        )
    )


def _day_items(
    items,
    day,
):
    result = []

    for item in items or []:
        parsed = _parse_date(
            item.get("date")
        )

        if (
            parsed
            and parsed.date()
            == day.date()
        ):
            result.append(
                item
            )

    return result


def _counter_row(
    icon,
    label,
    value,
    color,
):
    if not value:
        return ft.Container(
            height=0
        )

    return ft.Row(
        controls=[
            ft.Text(
                icon,
                size=8,
                color=color,
            ),
            ft.Text(
                f"{value} {label}",
                size=9,
                color=color,
                weight=(
                    ft.FontWeight.W_600
                ),
            ),
        ],
        spacing=4,
    )


def _day_cell(
    day,
    month_anchor,
    items,
    on_day_click=None,
):
    today = datetime.now().date()

    in_month = (
        day.month
        == month_anchor.month
        and day.year
        == month_anchor.year
    )

    is_today = (
        day.date()
        == today
    )

    tasks = [
        item
        for item in items
        if item.get(
            "item_type"
        )
        == "TASK"
    ]

    alerts = [
        item
        for item in items
        if item.get(
            "item_type"
        )
        == "ALERT"
    ]

    critical = [
        item
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
    ]

    return ft.Container(
        expand=True,
        height=56,
        ink=True,
        on_click=(
            None
            if on_day_click is None
            else lambda e:
                on_day_click(day)
        ),
        bgcolor=(
            "#EEF6FF"
            if is_today
            else (
                "#FFFFFF"
                if in_month
                else "#F8FAFC"
            )
        ),
        border=ft.border.only(
            right=ft.BorderSide(
                1,
                Q_BORDER,
            ),
            bottom=ft.BorderSide(
                1,
                Q_BORDER,
            ),
        ),
        padding=6,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            width=24,
                            height=20,
                            alignment=(
                                ft.Alignment(
                                    0,
                                    0,
                                )
                            ),
                            border_radius=999,
                            bgcolor=(
                                Q_PRIMARY
                                if is_today
                                else None
                            ),
                            content=ft.Text(
                                str(
                                    day.day
                                ),
                                size=10,
                                weight=(
                                    ft.FontWeight.BOLD
                                ),
                                color=(
                                    "#FFFFFF"
                                    if is_today
                                    else (
                                        Q_PRIMARY_DARK
                                        if in_month
                                        else "#98A2B3"
                                    )
                                ),
                            ),
                        ),
                        ft.Container(
                            expand=True
                        ),
                        (
                            ft.Text(
                                str(
                                    len(items)
                                ),
                                size=8,
                                color=Q_MUTED,
                            )
                            if items
                            else ft.Container()
                        ),
                    ],
                    spacing=2,
                ),
                ft.Column(
                    controls=[
                        _counter_row(
                            "●",
                            (
                                "tarea"
                                if len(tasks)
                                == 1
                                else "tareas"
                            ),
                            len(tasks),
                            Q_PRIMARY,
                        ),
                        _counter_row(
                            "●",
                            (
                                "aviso"
                                if len(alerts)
                                == 1
                                else "avisos"
                            ),
                            len(alerts),
                            "#B54708",
                        ),
                        _counter_row(
                            "●",
                            "crítico",
                            len(critical),
                            "#B42318",
                        ),
                    ],
                    spacing=0,
                ),
            ],
            spacing=1,
        ),
    )


def calendar_month_grid(
    items,
    month_anchor,
    on_day_click=None,
):
    anchor = month_anchor.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    grid_start = _month_grid_start(
        anchor
    )

    header = ft.Row(
        controls=[
            ft.Container(
                expand=True,
                height=30,
                bgcolor="#F8FAFC",
                alignment=(
                    ft.Alignment(
                        0,
                        0,
                    )
                ),
                border=ft.border.only(
                    right=ft.BorderSide(
                        1,
                        Q_BORDER,
                    ),
                    bottom=ft.BorderSide(
                        1,
                        Q_BORDER,
                    ),
                ),
                content=ft.Text(
                    name,
                    size=10,
                    weight=(
                        ft.FontWeight.BOLD
                    ),
                    color=Q_PRIMARY_DARK,
                ),
            )
            for name in DAY_NAMES
        ],
        spacing=0,
    )

    rows = [
        header
    ]

    for week_index in range(6):
        controls = []

        for day_index in range(7):
            day = (
                grid_start
                + timedelta(
                    days=(
                        week_index * 7
                        + day_index
                    )
                )
            )

            controls.append(
                _day_cell(
                    day,
                    anchor,
                    _day_items(
                        items,
                        day,
                    ),
                    on_day_click=(
                        on_day_click
                    ),
                )
            )

        rows.append(
            ft.Row(
                controls=controls,
                spacing=0,
            )
        )

    return ft.Container(
        height=390,
        bgcolor="#FFFFFF",
        border=ft.border.all(
            1,
            Q_BORDER,
        ),
        border_radius=14,
        clip_behavior=(
            ft.ClipBehavior.HARD_EDGE
        ),
        content=ft.Column(
            controls=rows,
            spacing=0,
        ),
    )
