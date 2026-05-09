import flet as ft

Q_BORDER = "#E4E7EC"
Q_TEXT = "#101828"
Q_MUTED = "#64748B"


def document_rule_row(document_name, pattern="", required=True, extensions="pdf,jpg,jpeg,png"):
    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=12,
        padding=12,
        content=ft.Row(
            controls=[
                ft.Text(document_name or "-", size=13, weight=ft.FontWeight.BOLD, color=Q_TEXT, expand=True),
                ft.Text("Obligatorio" if required else "Opcional", size=12, color=Q_MUTED, width=90),
                ft.Text(pattern or "-", size=12, color=Q_TEXT, width=180),
                ft.Text(extensions or "-", size=12, color=Q_MUTED, width=120),
            ],
            spacing=12,
        ),
    )
