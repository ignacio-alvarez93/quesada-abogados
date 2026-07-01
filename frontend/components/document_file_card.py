from pathlib import Path

import flet as ft

from frontend.components.app_button import primary_button, secondary_button, danger_button


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_BORDER = "#D0D5DD"
Q_MUTED = "#64748B"


def _file_icon(file_type=None, file_name=None):
    raw_type = str(file_type or "").lower().strip()
    name = str(file_name or "").lower().strip()
    suffix = Path(name).suffix.lower()

    if raw_type == "pdf" or suffix == ".pdf":
        return ft.Icons.PICTURE_AS_PDF

    if raw_type == "image" or suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        return ft.Icons.IMAGE

    return ft.Icons.DESCRIPTION


def document_file_card(
    name,
    path=None,
    relative_path=None,
    folder=None,
    size_label=None,
    modified_at=None,
    file_type=None,
    selected=False,
    selectable=False,
    on_select=None,
    on_preview=None,
    on_open=None,
    preview_label="Ver",
    open_label="Abrir",
    extra_lines=None,
    extra_actions=None,
    action_groups=None,
    compact=False,
):
    """
    Tarjeta visual reutilizable para documentos.

    No abre archivos ni genera previews directamente.
    La vista consumidora inyecta callbacks:
    - on_preview
    - on_open
    - on_select
    - extra_actions
    """
    display_name = str(name or "-")
    display_path = str(path or "")
    display_relative = str(relative_path or "")
    display_folder = str(folder or "")
    display_size = str(size_label or "")
    display_modified = str(modified_at or "")

    metadata = []

    if display_folder:
        metadata.append(f"Carpeta: {display_folder}")

    if display_size or display_modified:
        metadata.append(" · ".join([part for part in [display_size, display_modified] if part]))

    controls = [
        ft.Row(
            controls=[
                ft.Icon(
                    _file_icon(file_type, display_name),
                    color=Q_PRIMARY,
                    size=18 if compact else 20,
                ),
                ft.Text(
                    display_name,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                    expand=True,
                    selectable=True,
                    size=12 if compact else 13,
                ),
                *(
                    [
                        ft.Checkbox(
                            label="" if compact else "Sel.",
                            value=bool(selected),
                            on_change=on_select,
                        )
                    ]
                    if selectable
                    else []
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    ]

    for line in metadata:
        controls.append(ft.Text(line, size=11, color=Q_MUTED, selectable=True))

    if display_relative:
        controls.append(ft.Text(display_relative, size=10 if compact else 11, color=Q_MUTED, selectable=True))

    if display_path:
        controls.append(ft.Text(display_path, size=10, color=Q_MUTED, selectable=True))

    for line in extra_lines or []:
        if isinstance(line, ft.Control):
            controls.append(line)
        elif line:
            controls.append(ft.Text(str(line), size=11, color=Q_MUTED, selectable=True))

    actions = []

    if on_preview:
        actions.append(primary_button(preview_label, on_preview))

    if on_open:
        actions.append(secondary_button(open_label, on_open))

    for action in extra_actions or []:
        if action is not None:
            actions.append(action)

    def _action_group_item_button(item):
        if isinstance(item, ft.Control):
            return item

        if isinstance(item, dict):
            label = str(item.get("label") or item.get("text") or "-")
            on_click = item.get("on_click")
            disabled = bool(item.get("disabled") or False)
            danger = bool(item.get("danger") or False)

            button_factory = danger_button if danger else secondary_button
            button = button_factory(label, on_click or (lambda e: None))
            button.disabled = disabled
            return button

        return secondary_button(str(item), lambda e: None)

    def _action_group_button(group):
        if isinstance(group, ft.Control):
            return group

        if not isinstance(group, dict):
            return None

        label = str(group.get("label") or group.get("title") or "Acciones")
        items = [item for item in (group.get("items") or []) if item is not None]

        if not items:
            return None

        return ft.Container(
            border=ft.border.all(1, Q_BORDER),
            border_radius=10,
            bgcolor="#FFFFFF",
            content=ft.ExpansionTile(
                title=ft.Text(
                    label,
                    size=12,
                    color=Q_PRIMARY_DARK,
                    weight=ft.FontWeight.BOLD,
                ),
                subtitle=ft.Text(
                    f"{len(items)} accion(es)",
                    size=10,
                    color=Q_MUTED,
                ),
                controls=[
                    ft.Container(
                        padding=ft.padding.only(left=10, right=10, bottom=10),
                        content=ft.Row(
                            controls=[_action_group_item_button(item) for item in items],
                            spacing=8,
                            wrap=True,
                        ),
                    )
                ],
            ),
        )

    for group in action_groups or []:
        group_button = _action_group_button(group)
        if group_button is not None:
            actions.append(group_button)

    if actions:
        controls.append(
            ft.Row(
                controls=actions,
                spacing=8,
                wrap=True,
            )
        )

    return ft.Container(
        padding=8 if compact else 10,
        border_radius=10,
        border=ft.border.all(1, Q_BORDER),
        bgcolor="#EFF8FF" if selected else "#FFFFFF",
        content=ft.Column(
            controls=controls,
            spacing=4 if compact else 5,
        ),
    )
