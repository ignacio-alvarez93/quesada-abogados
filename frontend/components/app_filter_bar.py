import flet as ft

Q_BORDER = "#D8E2EE"


def filter_bar(dropdown, search_input, actions=None):
    return ft.Container(
        content=ft.Row(
            controls=[
                dropdown,
                search_input,
                ft.Container(expand=True),
                *(actions or []),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=14,
    )
