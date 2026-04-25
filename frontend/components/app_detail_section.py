import flet as ft

Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D8E2EE"
Q_MUTED = "#64748B"
Q_TEXT = "#0F172A"


def detail_section(title, fields):
    controls = [ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)]
    for label, value in fields:
        controls.append(
            ft.Row(
                controls=[
                    ft.Text(f"{label}:", width=180, size=13, color=Q_MUTED, weight=ft.FontWeight.BOLD),
                    ft.Text(str(value or "-"), size=13, color=Q_TEXT, expand=True),
                ],
                spacing=10,
            )
        )
    return ft.Container(
        content=ft.Column(controls=controls, spacing=10),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=18,
    )
