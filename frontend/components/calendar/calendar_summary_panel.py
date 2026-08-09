import flet as ft

from frontend.components.app_card import (
    info_card,
)


Q_PRIMARY = "#0057B8"
Q_MUTED = "#64748B"
Q_SUCCESS = "#027A48"
Q_WARNING = "#B54708"


def _summary_row(
    label,
    value,
    color=None,
):
    return ft.Row(
        controls=[
            ft.Text(
                label,
                size=12,
                color=Q_MUTED,
                expand=True,
            ),
            ft.Text(
                str(value),
                size=12,
                weight=ft.FontWeight.BOLD,
                color=color or "#0F172A",
            ),
        ],
        spacing=8,
    )


def calendar_summary_panel(
    summary,
    upcoming,
    on_select_item=None,
):
    summary = summary or {}
    upcoming = upcoming or []

    day_card = info_card(
        "Resumen operativo",
        ft.Column(
            controls=[
                _summary_row(
                    "Tareas pendientes",
                    summary.get(
                        "pending_tasks",
                        0,
                    ),
                ),
                _summary_row(
                    "Vencen hoy",
                    summary.get(
                        "due_today",
                        0,
                    ),
                ),
                _summary_row(
                    "Próximos 7 días",
                    summary.get(
                        "next_7_days",
                        0,
                    ),
                ),
                _summary_row(
                    "Avisos críticos",
                    summary.get(
                        "critical_alerts",
                        0,
                    ),
                    "#D92D20",
                ),
            ],
            spacing=8,
        ),
    )

    expiry_controls = []

    for item in upcoming:
        expiry_controls.append(
            ft.Container(
                ink=True,
                border_radius=8,
                padding=ft.padding.symmetric(
                    horizontal=4,
                    vertical=4,
                ),
                on_click=(
                    None
                    if on_select_item is None
                    else lambda e,
                    current=item:
                        on_select_item(
                            current
                        )
                ),
                content=ft.Row(
                    controls=[
                        ft.Text(
                            "●",
                            size=10,
                            color=(
                                Q_WARNING
                                if item.get(
                                    "item_type"
                                )
                                == "ALERT"
                                else Q_PRIMARY
                            ),
                        ),
                        ft.Text(
                            item.get("title")
                            or "-",
                            size=11,
                            color="#0F172A",
                            expand=True,
                            overflow=(
                                ft.TextOverflow
                                .ELLIPSIS
                            ),
                        ),
                        ft.Text(
                            str(
                                item.get("date")
                                or ""
                            )[:10],
                            size=10,
                            color=Q_MUTED,
                        ),
                    ],
                    spacing=6,
                ),
            )
        )

    if not expiry_controls:
        expiry_controls.append(
            ft.Text(
                "Sin vencimientos próximos",
                size=11,
                color=Q_MUTED,
            )
        )

    expiry_card = info_card(
        "Próximos vencimientos",
        ft.Container(
            height=125,
            content=ft.Column(
                controls=expiry_controls,
                spacing=4,
                scroll=ft.ScrollMode.AUTO,
            ),
        ),
    )

    telegram_card = info_card(
        "Alertas Telegram",
        ft.Column(
            controls=[
                _summary_row(
                    "Bot",
                    "Configurado",
                    Q_SUCCESS,
                ),
                _summary_row(
                    "Pendientes",
                    summary.get(
                        "pending_telegram",
                        0,
                    ),
                    (
                        Q_WARNING
                        if summary.get(
                            "pending_telegram",
                            0,
                        )
                        else Q_SUCCESS
                    ),
                ),
            ],
            spacing=8,
        ),
    )

    return ft.Column(
        controls=[
            day_card,
            expiry_card,
            telegram_card,
        ],
        spacing=12,
    )
