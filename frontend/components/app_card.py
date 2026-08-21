import flet as ft

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_ACCENT = "#18BFEA"
Q_BORDER = "#D8E2EE"
Q_TEXT = "#0F172A"
Q_MUTED = "#64748B"


def info_card(title, content):
    if not isinstance(content, ft.Control):
        content = ft.Text(str(content), size=13, color=Q_TEXT)
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                content,
            ],
            spacing=8,
        ),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=18,
    )


def metric_card(
    title,
    value,
    icon=None,
    accent_color=None,
    subtitle=None,
    width=220,
    horizontal=False,
):
    """
    Card reutilizable de métrica.

    Compatible con el contrato histórico:
        metric_card(title, value)

    horizontal=True activa la variante dashboard:
    icono lateral + contenido jerarquizado.
    """
    accent = accent_color or Q_PRIMARY

    if (
        icon is None
        and subtitle is None
        and accent_color is None
    ):
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        title,
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        str(value),
                        size=26,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY,
                    ),
                ],
                spacing=4,
            ),
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=18,
            width=width,
        )

    icon_control = None

    if icon is not None:
        icon_control = ft.Container(
            width=48 if horizontal else 36,
            height=48 if horizontal else 36,
            alignment=ft.Alignment(0, 0),
            border_radius=13 if horizontal else 10,
            bgcolor="#F8FAFC",
            border=ft.border.all(
                1,
                Q_BORDER,
            ),
            content=ft.Icon(
                icon,
                size=23 if horizontal else 19,
                color=accent,
            ),
        )

    if horizontal:
        text_controls = [
            ft.Text(
                title,
                size=12,
                color=Q_MUTED,
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                str(value),
                size=28,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
        ]

        if subtitle:
            text_controls.append(
                ft.Text(
                    str(subtitle),
                    size=10,
                    color=Q_MUTED,
                )
            )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=15,
            padding=16,
            width=width,
            content=ft.Row(
                controls=[
                    icon_control,
                    ft.Column(
                        controls=text_controls,
                        spacing=3,
                        expand=True,
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    header_controls = []

    if icon_control is not None:
        header_controls.append(icon_control)

    header_controls.append(
        ft.Text(
            title,
            size=12,
            color=Q_MUTED,
            weight=ft.FontWeight.W_600,
        )
    )

    controls = [
        ft.Row(
            controls=header_controls,
            spacing=9,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Text(
            str(value),
            size=28,
            weight=ft.FontWeight.BOLD,
            color=Q_PRIMARY_DARK,
        ),
    ]

    if subtitle:
        controls.append(
            ft.Text(
                str(subtitle),
                size=10,
                color=Q_MUTED,
            )
        )

    return ft.Container(
        content=ft.Column(
            controls=controls,
            spacing=7,
        ),
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=16,
        width=width,
    )
