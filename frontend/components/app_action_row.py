import flet as ft


def action_row(actions):
    return ft.Row(
        controls=actions or [],
        spacing=10,
        alignment=ft.MainAxisAlignment.END,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
