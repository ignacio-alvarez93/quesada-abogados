import flet as ft

Q_PRIMARY = "#0057B8"
Q_BORDER = "#CBD5E1"
Q_FOCUSED = "#18BFEA"


def select_input(label, options, value=None, width=None, on_change=None):
    return ft.Dropdown(
        label=label,
        value=value,
        width=width,
        on_change=on_change,
        options=[ft.dropdown.Option(option) for option in options],
        border_radius=10,
        border_color=Q_BORDER,
        focused_border_color=Q_FOCUSED,
        color=Q_PRIMARY,
        content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
    )
