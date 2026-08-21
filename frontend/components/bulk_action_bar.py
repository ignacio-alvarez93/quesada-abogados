import flet as ft

Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D0D5DD"
Q_MUTED = "#64748B"
Q_DISABLED = "#98A2B3"
Q_DANGER = "#B42318"


def _action_visible(action):
    if action is None:
        return False
    if isinstance(action, dict):
        return bool(action.get("visible", True))
    return True


def _action_disabled(action, selected_count):
    if not isinstance(action, dict):
        return False

    if "disabled" in action:
        return bool(action.get("disabled"))

    return bool(action.get("disable_when_empty", True)) and int(selected_count or 0) <= 0


def _action_color(action, selected_count):
    if not isinstance(action, dict):
        return Q_PRIMARY_DARK

    disabled = _action_disabled(action, selected_count)
    if disabled:
        return Q_DISABLED

    if action.get("danger"):
        return Q_DANGER

    return action.get("color") or Q_PRIMARY_DARK


def bulk_action_bar(
    *,
    title=None,
    selected_count=0,
    actions=None,
    on_clear=None,
    clear_tooltip="Limpiar selección",
    message_control=None,
    compact=True,
    inline=False,
):
    """
    Barra reusable para acciones masivas.

    Regla visual:
    - selected_count == 0: acciones desactivadas por defecto.
    - danger=True: acción roja cuando está activa.
    - on_clear: añade icono de limpiar selección.
    - actions: lista de dicts con icon, tooltip, on_click, danger, disabled, visible.
    """

    selected_count = int(selected_count or 0)
    has_selected = selected_count > 0
    actions = [action for action in (actions or []) if _action_visible(action)]

    row_controls = []

    if title:
        row_controls.append(
            ft.Text(
                str(title),
                size=13 if compact else 14,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            )
        )

    row_controls.append(
        ft.Text(
            f"Seleccionados: {selected_count}",
            size=11 if compact else 12,
            weight=ft.FontWeight.BOLD if not compact else None,
            color=Q_PRIMARY_DARK if has_selected else Q_MUTED,
        )
    )

    if on_clear is not None:
        row_controls.append(
            ft.IconButton(
                icon=ft.Icons.CLEAR_ALL,
                icon_color=Q_PRIMARY_DARK if has_selected else Q_DISABLED,
                tooltip=clear_tooltip,
                disabled=not has_selected,
                on_click=on_clear,
            )
        )

    for action in actions:
        if isinstance(action, ft.Control):
            row_controls.append(action)
            continue

        if not isinstance(action, dict):
            continue

        row_controls.append(
            ft.IconButton(
                icon=action.get("icon") or ft.Icons.MORE_HORIZ,
                icon_color=_action_color(action, selected_count),
                tooltip=str(action.get("tooltip") or action.get("label") or "Acción"),
                disabled=_action_disabled(action, selected_count),
                on_click=action.get("on_click"),
            )
        )

    controls = [
        ft.Row(
            controls=row_controls,
            spacing=6 if compact else 8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    ]

    if message_control is not None:
        controls.append(message_control)

    if inline:
        return ft.Column(
            controls=controls,
            spacing=4,
            tight=True,
        )

    return ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=10 if compact else 14,
        padding=8 if compact else 10,
        content=ft.Column(
            controls=controls,
            spacing=6,
        ),
    )
