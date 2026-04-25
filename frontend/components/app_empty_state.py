import flet as ft

Q_PRIMARY = "#0057B8"
Q_MUTED = "#64748B"
Q_BORDER = "#D8E2EE"


def empty_state(message):
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Icon(ft.Icons.INBOX_OUTLINED, size=46, color=Q_PRIMARY),
                ft.Text(message, size=15, color=Q_MUTED, text_align=ft.TextAlign.CENTER),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        alignment=ft.alignment.center,
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=32,
        expand=True,
    )
