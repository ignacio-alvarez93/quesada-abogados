import flet as ft

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_ACCENT = "#18BFEA"
Q_DANGER = "#D92D20"
Q_TEXT = "#0F172A"
Q_WHITE = "#FFFFFF"
Q_BORDER_RADIUS = 10


def _button_style(bgcolor: str, color: str = Q_WHITE, height: int = 42) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        bgcolor=bgcolor,
        color=color,
        shape=ft.RoundedRectangleBorder(radius=Q_BORDER_RADIUS),
        padding=ft.padding.symmetric(horizontal=18, vertical=10),
    )


def primary_button(text, on_click):
    return ft.ElevatedButton(
        text=text,
        on_click=on_click,
        height=42,
        style=_button_style(Q_PRIMARY),
    )


def secondary_button(text, on_click):
    return ft.OutlinedButton(
        text=text,
        on_click=on_click,
        height=42,
        style=ft.ButtonStyle(
            color=Q_PRIMARY,
            side=ft.BorderSide(1, Q_PRIMARY),
            shape=ft.RoundedRectangleBorder(radius=Q_BORDER_RADIUS),
            padding=ft.padding.symmetric(horizontal=18, vertical=10),
        ),
    )


def danger_button(text, on_click):
    return ft.ElevatedButton(
        text=text,
        on_click=on_click,
        height=42,
        style=_button_style(Q_DANGER),
    )


def small_button(text, on_click):
    return ft.ElevatedButton(
        text=text,
        on_click=on_click,
        height=34,
        style=ft.ButtonStyle(
            bgcolor=Q_ACCENT,
            color=Q_WHITE,
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
        ),
    )
