import flet as ft

Q_PRIMARY = "#0057B8"
Q_ACCENT = "#18BFEA"
Q_TEXT = "#101828"
Q_MUTED = "#667085"


def app_loader(message="Cargando..."):
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.ProgressRing(
                    color=Q_PRIMARY,
                    width=36,
                    height=36,
                    stroke_width=4,
                ),
                ft.Text(
                    value=message,
                    size=13,
                    color=Q_MUTED,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        ),
        height=180,
        bgcolor="#FFFFFF",
        border_radius=12,
        border=ft.border.all(1, "#E4E7EC"),
    )


def app_progress_bar(value=0, message="Procesando..."):
    """
    value debe estar entre 0 y 1.
    Ejemplo:
    0.25 = 25%
    0.50 = 50%
    1.00 = 100%
    """

    if value < 0:
        value = 0

    if value > 1:
        value = 1

    percentage = int(value * 100)

    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(
                    value=message,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=Q_TEXT,
                ),
                ft.ProgressBar(
                    value=value,
                    color=Q_PRIMARY,
                    bgcolor="#E4E7EC",
                    height=8,
                ),
                ft.Text(
                    value=f"{percentage}%",
                    size=12,
                    color=Q_MUTED,
                ),
            ],
            spacing=8,
        ),
        padding=16,
        bgcolor="#FFFFFF",
        border_radius=12,
        border=ft.border.all(1, "#E4E7EC"),
    )