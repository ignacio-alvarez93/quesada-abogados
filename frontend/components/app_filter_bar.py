import flet as ft


def filter_bar(dropdown, search_input, actions=None):
    action_controls = []

    if actions is None:
        action_controls = []
    elif isinstance(actions, list):
        action_controls = actions
    else:
        action_controls = [actions]

    return ft.Container(
        content=ft.Row(
            controls=[
                dropdown,
                search_input,
                *action_controls,
            ],
            spacing=12,
            wrap=True,
        ),
        padding=12,
        bgcolor="#FFFFFF",
        border_radius=12,
        border=ft.border.all(1, "#E4E7EC"),
    )