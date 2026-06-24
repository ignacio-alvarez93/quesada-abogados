import flet as ft

from backend.services import document_inbox_service
from backend.services import document_viewer_service
from frontend.components.app_alert import error_alert, success_alert
from frontend.components.app_button import primary_button, secondary_button, danger_button
from frontend.components.app_empty_state import empty_state
from frontend.components.app_text_field import text_input, multiline_input
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.components.document_viewer_modal import open_document_viewer_modal


Q_PRIMARY_DARK = "#003B7A"
Q_PRIMARY = "#0057B8"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"


STATUS_LABELS = {
    "all": "Todos",
    "pending": "Pendientes",
    "linked": "Vinculados",
    "copied_to_box": "Copiados a Box",
    "reviewed": "Revisados",
    "discarded": "Descartados",
    "error": "Error",
}


def _format_size(size_bytes):
    try:
        size = int(size_bytes or 0)
    except Exception:
        return "-"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _status_chip(status):
    status = status or "pending"
    colors = {
        "pending": ("#FFF7ED", "#B54708"),
        "linked": ("#EFF8FF", "#175CD3"),
        "copied_to_box": ("#ECFDF3", "#027A48"),
        "reviewed": ("#F0F9FF", "#026AA2"),
        "discarded": ("#F2F4F7", "#475467"),
        "error": ("#FEF3F2", "#B42318"),
    }
    bg, fg = colors.get(status, ("#F8FAFC", Q_MUTED))
    return ft.Container(
        bgcolor=bg,
        border_radius=999,
        padding=ft.padding.symmetric(horizontal=10, vertical=4),
        content=ft.Text(
            STATUS_LABELS.get(status, status),
            size=11,
            color=fg,
            weight=ft.FontWeight.BOLD,
        ),
    )


def document_inbox_view(page: ft.Page):
    document_inbox_service.ensure_document_inbox_schema()

    client_options = document_inbox_service.client_autocomplete_options()
    client_label_to_id = {item["label"]: int(item["id"]) for item in client_options}

    state = {
        "items": [],
        "selected_item_id": None,
        "status_filter": "pending",
        "selected_client_id": None,
        "selected_expedient_id": None,
        "expedient_label_to_id": {},
    }

    message_box = ft.Column(spacing=6)

    status_dropdown = ft.Dropdown(
        label="Estado",
        width=220,
        value="pending",
        options=[ft.dropdown.Option(key, label) for key, label in STATUS_LABELS.items()],
    )

    manual_path = text_input("Ruta del archivo a importar manualmente", width=720)
    source_label = text_input("Origen / etiqueta", width=260)
    notes_field = multiline_input("Notas", width=720)

    box_subfolder = text_input("Subcarpeta Box destino opcional", width=300)

    selected_label = ft.Text("Ningún documento seleccionado", size=12, color=Q_MUTED)
    selected_relation_label = ft.Text("Cliente/expediente no seleccionado", size=12, color=Q_MUTED)

    items_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    preview_dialog = ft.AlertDialog(modal=True)
    viewer_overlay = {"control": None}

    def show_error(message):
        message_box.controls = [error_alert(str(message))]
        page.update()

    def show_success(message):
        message_box.controls = [success_alert(str(message))]
        page.update()

    def selected_item():
        item_id = state.get("selected_item_id")
        if not item_id:
            raise ValueError("Selecciona primero un documento de la bandeja.")
        return document_inbox_service.get_inbox_item(int(item_id))

    def client_options_labels():
        return [item["label"] for item in client_options]

    def build_expedient_options_for_client(client_id):
        options = document_inbox_service.expedient_autocomplete_options_for_client(int(client_id))
        state["expedient_label_to_id"] = {item["label"]: int(item["id"]) for item in options}
        return [item["label"] for item in options]

    def refresh_relation_label():
        cid = state.get("selected_client_id")
        eid = state.get("selected_expedient_id")
        selected_relation_label.value = f"Cliente ID: {cid or '-'} · Expediente ID: {eid or '-'}"

    def on_client_selected(value):
        state["selected_client_id"] = client_label_to_id.get(value)
        state["selected_expedient_id"] = None

        expedient_labels = []
        if state["selected_client_id"]:
            expedient_labels = build_expedient_options_for_client(state["selected_client_id"])

        expedient_autocomplete.set_options(expedient_labels, clear_value=True)
        expedient_autocomplete.input.label = (
            f"Expediente del cliente ({len(expedient_labels)})"
            if expedient_labels
            else "Expediente del cliente (sin expedientes)"
        )

        refresh_relation_label()
        page.update()

    def on_expedient_selected(value):
        state["selected_expedient_id"] = state["expedient_label_to_id"].get(value)
        refresh_relation_label()
        page.update()

    client_autocomplete = AppAutocomplete(
        page=page,
        label="Cliente",
        options=client_options_labels(),
        width=520,
        max_results=12,
        on_select=on_client_selected,
        allow_free_text=False,
    )

    expedient_autocomplete = AppAutocomplete(
        page=page,
        label="Expediente del cliente",
        options=[],
        width=620,
        max_results=12,
        on_select=on_expedient_selected,
        allow_free_text=False,
    )

    def refresh_items(e=None):
        state["status_filter"] = status_dropdown.value or "pending"
        state["items"] = document_inbox_service.list_inbox_items(status=state["status_filter"])
        render_items()

    def select_item(item_id):
        state["selected_item_id"] = int(item_id)
        item = document_inbox_service.get_inbox_item(int(item_id))
        selected_label.value = f"Seleccionado: #{item['id']} · {item.get('original_filename') or '-'}"

        if item.get("client_id"):
            state["selected_client_id"] = int(item.get("client_id"))
            expedient_labels = build_expedient_options_for_client(state["selected_client_id"])
            expedient_autocomplete.set_options(expedient_labels, clear_value=True)

        if item.get("expedient_id"):
            state["selected_expedient_id"] = int(item.get("expedient_id"))

        refresh_relation_label()
        render_items()

    def import_manual(e=None):
        try:
            path = (manual_path.value or "").strip().strip('"')
            if not path:
                raise ValueError("Indica la ruta del archivo a importar.")
            item = document_inbox_service.import_file_to_inbox(
                path,
                source_type="manual",
                source_label=source_label.value or "Manual",
                notes=notes_field.value or "",
            )
            manual_path.value = ""
            notes_field.value = ""
            show_success(f"Documento importado a bandeja: #{item['id']}")
            refresh_items()
        except Exception as exc:
            show_error(exc)

    def open_system(e=None):
        try:
            item = selected_item()
            document_inbox_service.open_inbox_item(item["id"])
        except Exception as exc:
            show_error(exc)

    def close_preview(e=None):
        try:
            preview_dialog.open = False
        except Exception:
            pass

        overlay = viewer_overlay.get("control")
        if overlay is not None:
            try:
                page.overlay.remove(overlay)
            except Exception:
                pass
            viewer_overlay["control"] = None

        page.update()

    def show_preview(e=None):
        try:
            item = selected_item()
            open_document_viewer_modal(
                page,
                item.get("stored_path"),
                title=item.get("original_filename") or "Documento de bandeja",
                expediente_id=None,
                initial_page=1,
                initial_zoom=1.6,
            )
        except Exception as exc:
            show_error(exc)

    def link_selected(e=None):
        try:
            item = selected_item()
            cid = state.get("selected_client_id")
            eid = state.get("selected_expedient_id")

            if not cid and not eid:
                raise ValueError("Selecciona un cliente o un expediente.")

            updated = document_inbox_service.link_inbox_item(
                item["id"],
                client_id=int(cid) if cid else None,
                expedient_id=int(eid) if eid else None,
            )
            show_success(f"Documento #{updated['id']} vinculado.")
            refresh_items()
        except Exception as exc:
            show_error(exc)

    def copy_to_box(e=None):
        try:
            item = selected_item()
            eid = state.get("selected_expedient_id") or item.get("expedient_id")
            if not eid:
                raise ValueError("Selecciona un expediente antes de copiar a Box.")

            updated = document_inbox_service.copy_inbox_item_to_expedient_box(
                item["id"],
                expedient_id=int(eid),
                subfolder=box_subfolder.value or "",
            )
            show_success(f"Documento copiado a Box: {updated.get('copied_to_box_path')}")
            refresh_items()
        except Exception as exc:
            show_error(exc)

    def set_status(status):
        try:
            item = selected_item()
            updated = document_inbox_service.update_inbox_item_status(item["id"], status)
            show_success(f"Documento #{updated['id']} marcado como {STATUS_LABELS.get(status, status)}.")
            refresh_items()
        except Exception as exc:
            show_error(exc)

    def render_items():
        selected_id = state.get("selected_item_id")
        rows = []

        for item in state.get("items", []):
            item_id = int(item.get("id"))
            selected = item_id == selected_id

            rows.append(
                ft.Container(
                    padding=10,
                    border_radius=12,
                    border=ft.border.all(2 if selected else 1, Q_PRIMARY if selected else Q_BORDER),
                    bgcolor="#EFF8FF" if selected else "#FFFFFF",
                    on_click=lambda e, item_id=item_id: select_item(item_id),
                    content=ft.Row(
                        controls=[
                            ft.Text("📄", size=20),
                            ft.Column(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.Text(f"#{item_id}", size=12, color=Q_MUTED),
                                            ft.Text(item.get("original_filename") or "-", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                            _status_chip(item.get("status")),
                                        ],
                                        spacing=8,
                                        wrap=True,
                                    ),
                                    ft.Text(item.get("stored_path") or "-", size=11, color=Q_MUTED, selectable=True),
                                    ft.Text(
                                        f"Origen: {item.get('source_type') or '-'} · {item.get('source_label') or '-'} · "
                                        f"Tamaño: {_format_size(item.get('size_bytes'))} · "
                                        f"Cliente ID: {item.get('client_id') or '-'} · Expediente ID: {item.get('expedient_id') or '-'}",
                                        size=11,
                                        color=Q_MUTED,
                                    ),
                                    ft.Text(
                                        f"Box destino: {item.get('copied_to_box_path') or '-'}",
                                        size=11,
                                        color=Q_MUTED,
                                        selectable=True,
                                    ),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                )
            )

        items_column.controls = rows or [
            empty_state("No hay documentos en esta bandeja para el filtro seleccionado.")
        ]

        try:
            selected_label.update()
            selected_relation_label.update()
            items_column.update()
        except Exception:
            pass

    status_dropdown.on_change = refresh_items

    header = ft.Row(
        controls=[
            ft.Text("Bandeja documental", size=26, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Container(expand=True),
            status_dropdown,
            secondary_button("Actualizar", refresh_items),
        ],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    import_box = ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=14,
        content=ft.Column(
            controls=[
                ft.Text("Entrada manual", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Text(
                    "Importa documentos recibidos por WhatsApp, email, descargas, escáner o justificantes. "
                    "El archivo se copia a la bandeja interna del ERP.",
                    size=12,
                    color=Q_MUTED,
                ),
                ft.Row([manual_path, source_label], spacing=10, wrap=True),
                notes_field,
                ft.Row(
                    controls=[
                        primary_button("Importar a bandeja", import_manual),
                    ],
                    spacing=10,
                ),
            ],
            spacing=10,
        ),
    )

    action_box = ft.Container(
        bgcolor="#FFFFFF",
        border=ft.border.all(1, Q_BORDER),
        border_radius=14,
        padding=14,
        content=ft.Column(
            controls=[
                ft.Text("Acciones sobre documento seleccionado", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                selected_label,
                selected_relation_label,
                ft.Row([client_autocomplete.control, expedient_autocomplete.control], spacing=10, wrap=True),
                ft.Row([box_subfolder], spacing=10, wrap=True),
                ft.Row(
                    controls=[
                        primary_button("Ver", show_preview),
                        secondary_button("Abrir original", open_system),
                        secondary_button("Vincular", link_selected),
                        primary_button("Copiar a Box expediente", copy_to_box),
                        secondary_button("Revisado", lambda e: set_status("reviewed")),
                        danger_button("Descartar", lambda e: set_status("discarded")),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
            spacing=10,
        ),
    )

    refresh_items()

    return ft.Container(
        expand=True,
        bgcolor="#F8FAFC",
        padding=20,
        content=ft.Column(
            controls=[
                header,
                ft.Text(
                    "Centro de entrada documental del ERP. Gestiona documentos recibidos antes de incorporarlos al expediente.",
                    size=13,
                    color=Q_MUTED,
                ),
                message_box,
                import_box,
                action_box,
                ft.Text("Documentos", size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                ft.Container(
                    expand=True,
                    content=items_column,
                ),
            ],
            spacing=14,
            expand=True,
        ),
    )
