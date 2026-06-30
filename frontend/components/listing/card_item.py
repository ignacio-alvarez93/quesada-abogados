import flet as ft

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D0D5DD"
Q_MUTED = "#64748B"


def card_item(
    title,
    subtitle=None,
    leading=None,
    badges=None,
    actions=None,
    title_controls=None,
    body=None,
    footer=None,
    selected=False,
    highlight=False,
    highlight_color="#FFF7E6",
    selected_color="#EFF8FF",
    border_color=None,
    border_width=None,
    on_click=None,
    padding=10,
):
    """
    Card/list item reutilizable.

    No conoce servicios, documentos, expedientes ni Box.
    Recibe controles ya construidos y los compone visualmente.
    """
    badges = badges or []
    actions = actions or []
    body = body or []
    footer = footer or []

    resolved_border_color = border_color or (Q_PRIMARY if selected else Q_BORDER)
    resolved_border_width = border_width or (2 if selected else 1)

    resolved_bg = "#FFFFFF"
    if highlight:
        resolved_bg = highlight_color
    elif selected:
        resolved_bg = selected_color

    header_controls = []

    if leading is not None:
        header_controls.append(leading)

    if title_controls is not None:
        header_row_controls = [control for control in title_controls if control is not None]
    else:
        header_row_controls = [
            ft.Text(
                str(title or "-"),
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            ),
            *badges,
            *actions,
        ]

    main_controls = [
        ft.Row(
            controls=header_row_controls,
            spacing=8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    ]

    if subtitle:
        main_controls.append(
            ft.Text(
                str(subtitle),
                size=11,
                color=Q_MUTED,
                selectable=True,
            )
        )

    for control in body:
        if control is not None:
            main_controls.append(control)

    for control in footer:
        if control is not None:
            main_controls.append(control)

    header_controls.append(
        ft.Column(
            controls=main_controls,
            spacing=3,
            expand=True,
        )
    )

    return ft.Container(
        padding=padding,
        border_radius=12,
        border=ft.border.all(resolved_border_width, resolved_border_color),
        bgcolor=resolved_bg,
        on_click=on_click,
        content=ft.Row(
            controls=header_controls,
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
    )
