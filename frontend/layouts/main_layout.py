import flet as ft

Q_BG = "#F5F9FF"


def main_layout(sidebar, content):
    return ft.Row(
        controls=[
            sidebar,
            ft.Container(
                content=content,
                expand=True,
                bgcolor=Q_BG,
                padding=24,
            ),
        ],
        spacing=0,
        expand=True,
    )
