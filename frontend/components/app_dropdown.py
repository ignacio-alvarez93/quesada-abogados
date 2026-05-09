import flet as ft

Q_PRIMARY = "#0057B8"
Q_BORDER = "#D0D5DD"


def select_input(label, options, value=None, width=None, on_change=None):
    dropdown = ft.Dropdown(
        label=label,
        value=value,
        width=width,
        border_color=Q_BORDER,
        focused_border_color=Q_PRIMARY,
        options=[
            ft.dropdown.Option(option)
            for option in options
        ],
    )

    if on_change is not None:
        dropdown.on_change = on_change

    return dropdown