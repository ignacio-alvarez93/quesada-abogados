import flet as ft

Q_DEFAULT_BG = "#EAF6FF"
Q_DEFAULT_FG = "#0057B8"


def expedient_status_badge(text, color=None):
    text = text or "-"
    fg = color or Q_DEFAULT_FG
    return ft.Container(
        content=ft.Text(
            text,
            size=12,
            weight=ft.FontWeight.BOLD,
            color=fg,
        ),
        bgcolor=_soft_bg(fg),
        border_radius=20,
        padding=ft.padding.symmetric(horizontal=10, vertical=5),
    )


def priority_badge(text, color=None):
    return expedient_status_badge(text or "-", color or Q_DEFAULT_FG)


def _soft_bg(color):
    mapping = {
        "#027A48": "#ECFDF3",
        "#B54708": "#FFFAEB",
        "#B42318": "#FEF3F2",
        "#475569": "#F1F5F9",
        "#0369A1": "#F0F9FF",
        "#026AA2": "#E0F2FE",
        "#0057B8": "#EAF3FF",
    }
    return mapping.get(color, Q_DEFAULT_BG)
