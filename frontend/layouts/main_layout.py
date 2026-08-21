import flet as ft

Q_BG = "#F5F9FF"


def main_layout(sidebar, content):
    return ft.Row(
        controls=[
            sidebar,
            ft.Container(
                content=content,
                expand=True,
                alignment=ft.Alignment(
                    -1,
                    -1,
                ),
                bgcolor=Q_BG,
                padding=ft.padding.only(
                    left=16,
                    top=16,
                    right=4,
                    bottom=16,
                ),
            ),
        ],
        spacing=0,
        expand=True,
    )