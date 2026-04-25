import flet as ft

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_ACCENT = "#18BFEA"
Q_BORDER = "#D8E2EE"
Q_TEXT = "#0F172A"
Q_MUTED = "#64748B"


def info_card(title, content):
    if not isinstance(content, ft.Control):
        content = ft.Text(str(content), size=13, color=Q_TEXT)
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content,
            ],
            spacing=8,
        ),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=18,
    )


def metric_card(title, value):
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(title, size=12, color=Q_MUTED),
                ft.Text(str(value), size=26, weight=ft.FontWeight.BOLD, color=Q_PRIMARY),
            ],
            spacing=4,
        ),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=18,
        width=220,
    )
