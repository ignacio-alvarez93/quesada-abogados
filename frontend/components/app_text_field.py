import flet as ft

Q_PRIMARY = "#0057B8"
Q_BORDER = "#CBD5E1"
Q_FOCUSED = "#18BFEA"


def _base_text_field(label, value="", width=None, multiline=False, min_lines=None, max_lines=None, height=None):
    return ft.TextField(
        label=label,
        value=value,
        width=width,
        height=height,
        multiline=multiline,
        min_lines=min_lines,
        max_lines=max_lines,
        border_radius=10,
        border_color=Q_BORDER,
        focused_border_color=Q_FOCUSED,
        cursor_color=Q_PRIMARY,
        content_padding=ft.padding.symmetric(horizontal=14, vertical=12),
    )


def text_input(label, value="", width=None):
    return _base_text_field(label=label, value=value, width=width)


def required_text_input(label, value="", width=None):
    return _base_text_field(label=f"{label} *", value=value, width=width)


def multiline_input(label, value="", width=None, height=None):
    return _base_text_field(
        label=label,
        value=value,
        width=width,
        height=height or 110,
        multiline=True,
        min_lines=3,
        max_lines=6,
    )
