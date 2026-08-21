import flet as ft


Q_BORDER = "#D8E2EE"
Q_TEXT = "#0F172A"
Q_MUTED = "#64748B"


def _filter_field(label, control, width=None):
    if width is not None and hasattr(control, "width"):
        control.width = width

    return ft.Column(
        controls=[
            ft.Text(
                label,
                size=11,
                color=Q_MUTED,
                weight=ft.FontWeight.W_500,
            ),
            control,
        ],
        spacing=6,
        tight=True,
    )


def filter_bar(
    dropdown=None,
    search_input=None,
    actions=None,
    fields=None,
    footer_actions=None,
):
    """
    Barra reusable de filtros.

    Contrato histórico:
        filter_bar(dropdown, search_input, actions)

    Variante enriquecida:
        filter_bar(fields=[...], footer_actions=[...])

    fields:
        [
            {
                "label": "...",
                "control": control,
                "width": 180,
            }
        ]
    """

    if fields is not None:
        field_controls = []

        for field in fields:
            if not isinstance(field, dict):
                continue

            control = field.get("control")

            if control is None:
                continue

            field_controls.append(
                _filter_field(
                    field.get("label") or "",
                    control,
                    field.get("width"),
                )
            )

        footer_controls = [
            item
            for item in (footer_actions or [])
            if item is not None
        ]

        controls = [
            ft.Row(
                controls=field_controls,
                spacing=12,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.END,
            )
        ]

        if footer_controls:
            controls.append(
                ft.Row(
                    controls=footer_controls,
                    spacing=8,
                    wrap=True,
                )
            )

        return ft.Container(
            content=ft.Column(
                controls=controls,
                spacing=12,
            ),
            padding=16,
            bgcolor="#FFFFFF",
            border_radius=14,
            border=ft.border.all(1, Q_BORDER),
        )

    action_controls = []

    if actions is None:
        action_controls = []
    elif isinstance(actions, list):
        action_controls = actions
    else:
        action_controls = [actions]

    return ft.Container(
        content=ft.Row(
            controls=[
                dropdown,
                search_input,
                *action_controls,
            ],
            spacing=12,
            wrap=True,
        ),
        padding=12,
        bgcolor="#FFFFFF",
        border_radius=12,
        border=ft.border.all(1, "#E4E7EC"),
    )
