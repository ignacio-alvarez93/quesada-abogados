import flet as ft

Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#E4E7EC"
Q_MUTED = "#64748B"


def config_section_card(title, subtitle, content, actions=None):
    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=16,
        padding=18,
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(title, size=22, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Text(subtitle, size=13, color=Q_MUTED),
                            ],
                            spacing=3,
                            expand=True,
                        ),
                        ft.Row(controls=actions or [], spacing=8),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=1, bgcolor=Q_BORDER),
                content,
            ],
            spacing=16,
        ),
    )
