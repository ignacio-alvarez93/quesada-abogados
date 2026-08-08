from datetime import datetime, timedelta

import flet as ft

from .calendar_event_card import (
    calendar_event_card,
)


Q_BORDER = "#E4E7EC"
Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"

DAY_NAMES = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]

HOURS = list(
    range(8, 19)
)


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


def _hour_for_item(item):
    parsed = _parse_date(
        item.get("date")
    )

    if not parsed:
        return None

    return max(
        8,
        min(
            18,
            parsed.hour,
        ),
    )


def _day_header(
    day,
    index,
):
    is_today = (
        day.date()
        == datetime.now().date()
    )

    return ft.Container(
        height=54,
        bgcolor=(
            "#EEF6FF"
            if is_today
            else "#F8FAFC"
        ),
        border=ft.border.only(
            bottom=ft.BorderSide(
                1,
                Q_BORDER,
            )
        ),
        alignment=ft.Alignment(
            0,
            0,
        ),
        content=ft.Column(
            controls=[
                ft.Text(
                    DAY_NAMES[index],
                    size=11,
                    weight=(
                        ft.FontWeight.BOLD
                    ),
                    color=(
                        Q_PRIMARY
                        if is_today
                        else Q_PRIMARY_DARK
                    ),
                ),
                ft.Text(
                    day.strftime(
                        "%d/%m"
                    ),
                    size=10,
                    color=Q_MUTED,
                ),
            ],
            spacing=1,
            horizontal_alignment=(
                ft.CrossAxisAlignment
                .CENTER
            ),
            alignment=(
                ft.MainAxisAlignment
                .CENTER
            ),
        ),
    )


def calendar_week_grid(
    items,
    week_start,
    on_item_click=None,
):
    days = [
        week_start
        + timedelta(days=index)
        for index in range(7)
    ]

    indexed = {
        (
            day.date(),
            hour,
        ): []
        for day in days
        for hour in HOURS
    }

    for item in items or []:
        parsed = _parse_date(
            item.get("date")
        )

        if not parsed:
            continue

        key = (
            parsed.date(),
            _hour_for_item(item),
        )

        if key in indexed:
            indexed[key].append(
                item
            )

    header_controls = [
        ft.Container(
            width=64,
            height=54,
            bgcolor="#F8FAFC",
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
        )
    ]

    for index, day in enumerate(days):
        header_controls.append(
            ft.Container(
                expand=True,
                border=ft.border.only(
                    right=ft.BorderSide(
                        1,
                        Q_BORDER,
                    )
                    if index < 6
                    else None,
                ),
                content=_day_header(
                    day,
                    index,
                ),
            )
        )

    rows = [
        ft.Row(
            controls=header_controls,
            spacing=0,
        )
    ]

    for hour in HOURS:
        controls = [
            ft.Container(
                width=64,
                height=58,
                alignment=ft.Alignment(
                    0,
                    -1,
                ),
                padding=ft.padding.only(
                    top=7,
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
                    f"{hour:02d}:00",
                    size=10,
                    color=Q_MUTED,
                ),
            )
        ]

        for index, day in enumerate(
            days
        ):
            events = indexed.get(
                (
                    day.date(),
                    hour,
                ),
                [],
            )

            event_controls = []

            for item in events[:2]:
                event_controls.append(
                    calendar_event_card(
                        item,
                        on_click=(
                            None
                            if on_item_click
                            is None
                            else lambda e,
                            current=item:
                                on_item_click(
                                    current
                                )
                        ),
                    )
                )

            if len(events) > 2:
                event_controls.append(
                    ft.Text(
                        (
                            f"+{len(events) - 2} "
                            "más"
                        ),
                        size=9,
                        color=Q_PRIMARY,
                        weight=(
                            ft.FontWeight
                            .W_600
                        ),
                    )
                )

            controls.append(
                ft.Container(
                    expand=True,
                    height=54,
                    padding=4,
                    border=ft.border.only(
                        right=ft.BorderSide(
                            1,
                            Q_BORDER,
                        )
                        if index < 6
                        else None,
                        bottom=ft.BorderSide(
                            1,
                            Q_BORDER,
                        ),
                    ),
                    bgcolor="#FFFFFF",
                    content=ft.Column(
                        controls=event_controls,
                        spacing=2,
                        scroll=(
                            ft.ScrollMode.AUTO
                            if event_controls
                            else None
                        ),
                    ),
                )
            )

        rows.append(
            ft.Row(
                controls=controls,
                spacing=0,
                vertical_alignment=(
                    ft.CrossAxisAlignment
                    .START
                ),
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
            ft.ClipBehavior
            .HARD_EDGE
        ),
        content=ft.Column(
            controls=rows,
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
        ),
    )
