import flet as ft

from .status_chip import status_chip

Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D0D5DD"
Q_MUTED = "#64748B"


def counter_chips(
    options,
    counts,
    active_value,
    on_select,
    include_all=True,
    all_label="Todos",
    all_value="all",
    status_map=None,
    status_aliases=None,
    bordered_status=False,
    direction="row",
):
    """
    Fila reutilizable de chips con contador.

    No conoce servicios ni módulos concretos.
    Recibe opciones, contadores, estado activo y callback.
    """
    controls = []

    normalized_active = str(active_value or all_value or "all").strip() or "all"
    safe_counts = counts or {}
    aliases = status_aliases or {}

    normalized_options = []

    if include_all:
        normalized_options.append((all_value, all_label))

    for option in options or []:
        if isinstance(option, dict):
            value = option.get("value") or option.get("status") or option.get("id")
            label = option.get("label") or option.get("name") or value
        else:
            value, label = option

        normalized_options.append((str(value), str(label)))

    for status_value, label in normalized_options:
        is_active = normalized_active == status_value or (
            status_value == all_value and normalized_active in ("", all_value)
        )

        count = safe_counts.get(status_value, 0)

        visual_status = aliases.get(status_value, status_value)

        chip = status_chip(
            visual_status,
            label=label,
            status_map=status_map,
            compact=True,
            bordered=bordered_status,
        )

        controls.append(
            ft.Container(
                bgcolor="#FFFFFF" if not is_active else "#EEF2FF",
                border=ft.border.all(1, Q_BORDER if not is_active else Q_PRIMARY),
                border_radius=999,
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                ink=True,
                on_click=lambda e, value=status_value: on_select(value),
                content=ft.Row(
                    controls=[
                        chip,
                        ft.Text(
                            str(count),
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color=Q_PRIMARY_DARK if is_active else Q_MUTED,
                        ),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
            )
        )

    if str(direction or "row").lower() in ("column", "vertical"):
        return ft.Column(
            controls=controls,
            spacing=8,
        )

    return ft.Row(
        controls=controls,
        spacing=8,
        wrap=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
