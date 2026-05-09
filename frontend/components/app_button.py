import flet as ft

Q_PRIMARY = "#0057B8"
Q_ACCENT = "#18BFEA"
Q_DANGER = "#D92D20"
Q_WHITE = "#FFFFFF"
Q_BORDER_RADIUS = 10


def _button_content(text: str) -> ft.Text:
    return ft.Text(
        value=text,
        color=Q_WHITE,
        weight=ft.FontWeight.W_600,
    )


def _button_style(bgcolor: str) -> ft.ButtonStyle:
    return ft.ButtonStyle(
        bgcolor=bgcolor,
        shape=ft.RoundedRectangleBorder(radius=Q_BORDER_RADIUS),
        padding=ft.padding.symmetric(horizontal=18, vertical=10),
    )


def primary_button(text, on_click):
    return ft.ElevatedButton(
        content=_button_content(text),
        on_click=on_click,
        height=42,
        style=_button_style(Q_PRIMARY),
    )


def secondary_button(text, on_click):
    return ft.OutlinedButton(
        content=ft.Text(
            value=text,
            color=Q_PRIMARY,
            weight=ft.FontWeight.W_600,
        ),
        on_click=on_click,
        height=42,
        style=ft.ButtonStyle(
            side=ft.BorderSide(1, Q_PRIMARY),
            shape=ft.RoundedRectangleBorder(radius=Q_BORDER_RADIUS),
            padding=ft.padding.symmetric(horizontal=18, vertical=10),
        ),
    )


def danger_button(text, on_click):
    return ft.ElevatedButton(
        content=_button_content(text),
        on_click=on_click,
        height=42,
        style=_button_style(Q_DANGER),
    )


def small_button(text, on_click):
    return ft.ElevatedButton(
        content=ft.Text(
            value=text,
            color=Q_WHITE,
            size=12,
            weight=ft.FontWeight.W_600,
        ),
        on_click=on_click,
        height=34,
        style=ft.ButtonStyle(
            bgcolor=Q_ACCENT,
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.padding.symmetric(horizontal=12, vertical=6),
        ),
    )