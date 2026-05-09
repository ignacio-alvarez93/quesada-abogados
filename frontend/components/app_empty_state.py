import flet as ft


def empty_state(message):
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(
                    value="📭",
                    size=40,
                ),
                ft.Text(
                    value=message,
                    size=14,
                    color="#667085",
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=200,
        bgcolor="#FFFFFF",
        border_radius=12,
        border=ft.border.all(1, "#E4E7EC"),
    )