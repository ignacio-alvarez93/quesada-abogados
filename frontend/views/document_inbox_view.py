import flet as ft

from backend.services import document_inbox_service
from backend.services import document_inbox_watch_service
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
        "all": ("#EEF2FF", "#3730A3"),
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
        "selected_item_ids": set(),
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

    def event_value(event, key, default=""):
        try:
            if hasattr(event, "get"):
                return event.get(key, default)
            return event[key]
        except Exception:
            return default

    def event_label(event_type):
        labels = {
            "imported": "Importado",
            "linked": "Vinculado",
            "status_changed": "Cambio de estado",
            "copied_to_box": "Copiado a Box",
            "opened": "Abierto",
            "rejected": "Rechazado",
            "restored": "Restaurado",
        }
        return labels.get(str(event_type or ""), str(event_type or "Evento"))

    def build_events_panel():
        item_id = state.get("selected_item_id")
        if not item_id:
            return ft.Container(
                padding=12,
                bgcolor="#F8FAFC",
                border_radius=12,
                border=ft.border.all(1, Q_BORDER),
                content=ft.Text(
                    "Selecciona un documento para ver su trazabilidad.",
                    size=12,
                    color=Q_MUTED,
                ),
            )

        try:
            item = document_inbox_service.get_inbox_item(item_id)
        except Exception:
            item = None

        if not item:
            return ft.Container(
                padding=12,
                bgcolor="#FEF3F2",
                border_radius=12,
                border=ft.border.all(1, "#FDA29B"),
                content=ft.Text("No se pudo cargar el documento seleccionado.", size=12, color="#B42318"),
            )

        try:
            events = document_inbox_service.get_inbox_events(item_id)
        except Exception as exc:
            events = []
            events_error = str(exc)
        else:
            events_error = ""

        file_name = str(item.get("original_filename") or item.get("stored_filename") or "-")
        status = str(item.get("status") or "-")
        source = " · ".join(
            part for part in [
                str(item.get("source_type") or "").strip(),
                str(item.get("source_label") or "").strip(),
            ]
            if part
        ) or "-"

        stored_path = str(item.get("stored_path") or "-")
        linked_path = str(item.get("linked_document_path") or "")
        copied_path = str(item.get("copied_to_box_path") or "")

        client_id = item.get("client_id") or "-"
        expedient_id = item.get("expedient_id") or "-"

        summary_controls = [
            ft.Row(
                controls=[
                    ft.Text(
                        "Documento seleccionado",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Container(expand=True),
                    secondary_button("Cerrar ficha", clear_selection),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(file_name, size=13, weight=ft.FontWeight.BOLD, color="#111827", selectable=True),
            ft.Row(
                controls=[
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=10, vertical=4),
                        border_radius=999,
                        bgcolor="#EFF6FF",
                        content=ft.Text(f"Estado: {status}", size=11, color=Q_PRIMARY_DARK),
                    ),
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=10, vertical=4),
                        border_radius=999,
                        bgcolor="#F8FAFC",
                        content=ft.Text(f"Fuente: {source}", size=11, color=Q_MUTED),
                    ),
                ],
                spacing=8,
                wrap=True,
            ),
            ft.Text(f"Cliente: {client_id} · Expediente: {expedient_id}", size=11, color=Q_MUTED),
            ft.Text(f"Ruta bandeja: {stored_path}", size=10, color=Q_MUTED, selectable=True),
        ]

        if copied_path:
            summary_controls.append(
                ft.Text(f"Copia Box: {copied_path}", size=10, color=Q_MUTED, selectable=True)
            )

        if linked_path:
            summary_controls.append(
                ft.Text(f"Vinculado: {linked_path}", size=10, color=Q_MUTED, selectable=True)
            )

        summary_controls.append(
            ft.Row(
                controls=[
                    primary_button("Ver documento", show_preview),
                    secondary_button("Abrir original", open_system),
                ],
                spacing=8,
                wrap=True,
            )
        )

        event_rows = []

        if events_error:
            event_rows.append(
                ft.Container(
                    padding=10,
                    bgcolor="#FEF3F2",
                    border_radius=10,
                    border=ft.border.all(1, "#FDA29B"),
                    content=ft.Text(
                        f"No se pudo cargar el historial: {events_error}",
                        size=11,
                        color="#B42318",
                    ),
                )
            )
        elif not events:
            event_rows.append(
                ft.Text("Este documento todavía no tiene eventos registrados.", size=12, color=Q_MUTED)
            )
        else:
            for event in events[:12]:
                created_at = str(event_value(event, "created_at", ""))
                event_type = event_label(event_value(event, "event_type", ""))
                message = str(event_value(event, "message", ""))
                event_rows.append(
                    ft.Container(
                        padding=10,
                        border=ft.border.all(1, "#E5E7EB"),
                        border_radius=10,
                        bgcolor="#FFFFFF",
                        content=ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(
                                            event_type,
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Container(expand=True),
                                        ft.Text(created_at, size=10, color=Q_MUTED),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(message or "Sin detalle", size=11, color="#334155", selectable=True),
                            ],
                            spacing=4,
                        ),
                    )
                )

        return ft.Container(
            padding=12,
            bgcolor="#F8FAFC",
            border_radius=12,
            border=ft.border.all(1, Q_BORDER),
            content=ft.Column(
                controls=[
                    ft.Container(
                        padding=12,
                        bgcolor="#FFFFFF",
                        border_radius=12,
                        border=ft.border.all(1, "#E5E7EB"),
                        content=ft.Column(controls=summary_controls, spacing=7),
                    ),
                    ft.Text(
                        "Historial de trazabilidad",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                    ft.Container(
                        height=220,
                        content=ft.ListView(
                            controls=event_rows,
                            spacing=6,
                            auto_scroll=False,
                        ),
                    ),
                ],
                spacing=10,
            ),
        )


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

    def build_status_counters():
        status_keys = [key for key in STATUS_LABELS.keys() if key != "all"]

        try:
            all_items = document_inbox_service.list_inbox_items(status=None, limit=2000)
        except TypeError:
            try:
                all_items = document_inbox_service.list_inbox_items(status=None)
            except Exception:
                all_items = []
        except Exception:
            all_items = []

        counts = {key: 0 for key in status_keys}
        total = 0

        for item in all_items:
            status = str(item.get("status") or "pending")
            if status in counts:
                counts[status] += 1
            total += 1

        current = state.get("status_filter") or "pending"

        def set_status_filter(status_value):
            status_dropdown.value = status_value
            refresh_items()

        chips = []

        chips.append(
            ft.Container(
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border_radius=999,
                bgcolor="#EEF2FF" if current == "all" else "#FFFFFF",
                border=ft.border.all(1, "#3730A3" if current == "all" else Q_BORDER),
                content=ft.Text(
                    f"Todos · {total}",
                    size=11,
                    color="#3730A3" if current == "all" else Q_MUTED,
                ),
                on_click=lambda e: set_status_filter("all"),
            )
        )

        for key in status_keys:
            selected = current == key
            label = STATUS_LABELS.get(key, key)
            chip = _status_chip(key)

            # Reutilizamos los colores visuales existentes cuando el chip está activo.
            active_bg = getattr(chip, "bgcolor", "#FFFFFF")
            active_border = "#D0D5DD"
            active_color = Q_PRIMARY_DARK

            chips.append(
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    border_radius=999,
                    bgcolor=active_bg if selected else "#FFFFFF",
                    border=ft.border.all(2 if selected else 1, active_color if selected else Q_BORDER),
                    content=ft.Text(
                        f"{label} · {counts.get(key, 0)}",
                        size=11,
                        weight=ft.FontWeight.BOLD if selected else ft.FontWeight.NORMAL,
                        color=active_color if selected else Q_MUTED,
                    ),
                    on_click=lambda e, s=key: set_status_filter(s),
                )
            )

        return ft.Container(
            padding=10,
            bgcolor="#FFFFFF",
            border_radius=12,
            border=ft.border.all(1, Q_BORDER),
            content=ft.Row(
                controls=chips,
                spacing=8,
                wrap=True,
            ),
        )

    def refresh_items(e=None):
        state["status_filter"] = status_dropdown.value or "pending"
        query_status = None if state["status_filter"] == "all" else state["status_filter"]
        state["items"] = document_inbox_service.list_inbox_items(status=query_status)
        status_counters_box.content = build_status_counters()
        render_items()
        try:
            status_dropdown.update()
        except Exception:
            pass
        try:
            status_counters_box.update()
        except Exception:
            pass
        try:
            items_column.update()
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    def clear_selection(e=None):
        state["selected_item_id"] = None
        state["selected_item_ids"] = set()
        state["selected_client_id"] = None
        state["selected_expedient_id"] = None
        selected_label.value = "Ningún documento seleccionado."
        client_autocomplete.set_options(
            document_inbox_service.client_autocomplete_options(),
            clear_value=True,
        )
        expedient_autocomplete.set_options([], clear_value=True)
        refresh_relation_label()
        events_box.content = build_events_panel()
        render_items()
        try:
            events_box.update()
        except Exception:
            pass
        page.update()

    def select_item(item_id):
        item_id = int(item_id)

        if state.get("selected_item_id") == item_id:
            clear_selection()
            return

        state["selected_item_id"] = item_id
        item = document_inbox_service.get_inbox_item(item_id)
        selected_label.value = f"Seleccionado: #{item['id']} · {item.get('original_filename') or '-'}"

        if item.get("client_id"):
            state["selected_client_id"] = int(item.get("client_id"))
            expedient_labels = build_expedient_options_for_client(state["selected_client_id"])
            expedient_autocomplete.set_options(expedient_labels, clear_value=True)

        if item.get("expedient_id"):
            state["selected_expedient_id"] = int(item.get("expedient_id"))

        refresh_relation_label()
        events_box.content = build_events_panel()
        render_items()
        try:
            events_box.update()
        except Exception:
            pass

    def toggle_item_selection(item_id):
        item_id = int(item_id)
        selected_ids = set(state.get("selected_item_ids") or set())

        if item_id in selected_ids:
            selected_ids.remove(item_id)
        else:
            selected_ids.add(item_id)

        state["selected_item_ids"] = selected_ids

        if selected_ids:
            selected_label.value = f"{len(selected_ids)} documento(s) seleccionado(s)."
        else:
            selected_label.value = "Ningún documento seleccionado."

        render_items()
        try:
            bulk_actions_box.content = build_bulk_actions_content()
        except Exception:
            pass
        try:
            selected_label.update()
        except Exception:
            pass
        try:
            bulk_actions_box.update()
        except Exception:
            pass
        try:
            items_column.update()
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    def import_manual(e=None):
        try:
            path = (manual_path.value or "").strip().strip('"')
            if not path:
                raise ValueError("Indica la ruta del archivo a importar.")
            item = document_inbox_service.import_file_to_inbox(
                path,
                source_type="manual",
                source_label=source_label.value or "Manual",
                notes="",
            )
            manual_path.value = ""
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
        selected_ids = set(state.get("selected_item_ids") or set())
        rows = []

        for item in state.get("items", []):
            item_id = int(item.get("id"))
            selected = item_id in selected_ids

            rows.append(
                ft.Container(
                    padding=10,
                    border_radius=12,
                    border=ft.border.all(2 if selected else 1, Q_PRIMARY if selected else Q_BORDER),
                    bgcolor="#EFF8FF" if selected else "#FFFFFF",
                    on_click=lambda e, item_id=item_id: toggle_item_selection(item_id),
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
                                            secondary_button("Ficha", lambda e, item_id=item_id: open_item_detail(item_id)),
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

    status_counters_box = ft.Container(content=build_status_counters())

    events_box = ft.Container(content=build_events_panel())

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

    def close_document_detail_dialog(e=None):
        dialog = state.get("document_detail_dialog")
        if dialog:
            dialog.open = False
        state["selected_item_id"] = None
        refresh_relation_label()
        try:
            page.update()
        except Exception:
            pass

    def open_document_detail_dialog(e=None):
        events_box.content = build_events_panel()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Ficha documental", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            content=ft.Container(
                width=980,
                height=720,
                content=ft.Column(
                    controls=[
                        ft.Container(
                            bgcolor="#F8FAFC",
                            border=ft.border.all(1, Q_BORDER),
                            border_radius=14,
                            padding=12,
                            content=ft.Column(
                                controls=[
                                    ft.Text("Documento y relación", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    selected_label,
                                    selected_relation_label,
                                    action_box,
                                ],
                                spacing=8,
                            ),
                        ),
                        ft.Container(
                            expand=True,
                            content=events_box,
                        ),
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                secondary_button("Cerrar", close_document_detail_dialog),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        state["document_detail_dialog"] = dialog
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def open_item_detail(item_id):
        state["selected_item_id"] = int(item_id)
        item = document_inbox_service.get_inbox_item(int(item_id))
        selected_label.value = f"Seleccionado para ficha: #{item['id']} · {item.get('original_filename') or '-'}"

        if item.get("client_id"):
            state["selected_client_id"] = int(item.get("client_id"))
            expedient_labels = build_expedient_options_for_client(state["selected_client_id"])
            expedient_autocomplete.set_options(expedient_labels, clear_value=True)

        if item.get("expedient_id"):
            state["selected_expedient_id"] = int(item.get("expedient_id"))

        refresh_relation_label()
        events_box.content = build_events_panel()
        open_document_detail_dialog()

    def close_import_dialog(e=None):
        dialog = state.get("import_dialog")
        if dialog:
            dialog.open = False
            try:
                page.update()
            except Exception:
                pass

    def open_import_dialog(e=None):
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Importar a bandeja", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            content=ft.Container(
                width=760,
                content=import_box,
            ),
            actions=[
                secondary_button("Cerrar", close_import_dialog),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        state["import_dialog"] = dialog
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    bulk_actions_message = ft.Container()

    def clear_bulk_selection(e=None):
        state["selected_item_ids"] = set()
        selected_label.value = "Ningún documento seleccionado."
        bulk_actions_message.content = None
        render_items()
        bulk_actions_box.content = build_bulk_actions_content()

        try:
            selected_label.update()
        except Exception:
            pass
        try:
            bulk_actions_box.update()
        except Exception:
            pass
        try:
            items_column.update()
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    def update_selected_documents_status(new_status, success_text):
        selected_ids = list(state.get("selected_item_ids") or [])

        if not selected_ids:
            bulk_actions_message.content = error_alert("Selecciona al menos un documento.")
            try:
                bulk_actions_message.update()
            except Exception:
                pass
            return

        ok = 0
        errors = []

        for item_id in selected_ids:
            try:
                try:
                    document_inbox_service.update_inbox_item_status(int(item_id), new_status)
                except TypeError:
                    document_inbox_service.update_inbox_item_status(
                        int(item_id),
                        new_status,
                        notes="Actualización en masa desde Bandeja Documental",
                    )
                ok += 1
            except Exception as exc:
                errors.append(f"#{item_id}: {exc}")

        state["selected_item_ids"] = set()
        selected_label.value = "Ningún documento seleccionado."

        if errors:
            bulk_actions_message.content = error_alert(
                f"{success_text}: {ok}. Errores: " + " | ".join(errors[:3])
            )
        else:
            bulk_actions_message.content = success_alert(f"{success_text}: {ok} documento(s).")

        refresh_items()
        bulk_actions_box.content = build_bulk_actions_content()

        try:
            selected_label.update()
        except Exception:
            pass
        try:
            bulk_actions_message.update()
        except Exception:
            pass
        try:
            bulk_actions_box.update()
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    def mark_selected_reviewed(e=None):
        update_selected_documents_status("reviewed", "Marcados como revisados")

    def discard_selected_documents(e=None):
        update_selected_documents_status("discarded", "Descartados")

    def build_bulk_actions_content():
        selected_count = len(state.get("selected_item_ids") or [])

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=10,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                f"Seleccionados: {selected_count}",
                                size=13,
                                weight=ft.FontWeight.BOLD,
                                color=Q_PRIMARY_DARK,
                            ),
                            ft.Container(expand=True),
                            secondary_button("Limpiar selección", clear_bulk_selection),
                            secondary_button("Marcar revisados", mark_selected_reviewed),
                            danger_button("Descartar", discard_selected_documents),
                            secondary_button("Agrupar documentos", lambda e: open_create_batch_dialog(e)),
                            secondary_button("Herramientas PDF", lambda e: None),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bulk_actions_message,
                ],
                spacing=8,
            ),
        )

    bulk_actions_box = ft.Container(content=build_bulk_actions_content())

    batches_panel_message = ft.Container()
    batches_list_box = ft.Column(spacing=6)

    def build_batches_panel_content():
        rows = []

        try:
            batches = document_inbox_service.list_document_inbox_batches(limit=20)
        except Exception as exc:
            return ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=14,
                padding=10,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text("Grupos documentales", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ft.Container(expand=True),
                                secondary_button("Refrescar grupos", refresh_batches_panel),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        error_alert(f"No se pudieron cargar grupos: {exc}"),
                    ],
                    spacing=8,
                ),
            )

        if not batches:
            rows.append(empty_state("Todavía no hay grupos documentales"))
        else:
            for batch in batches:
                batch_id = batch.get("id")
                name = batch.get("name") or "-"
                status = batch.get("status") or "draft"
                item_count = batch.get("item_count") or 0
                updated_at = batch.get("updated_at") or ""

                rows.append(
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=10,
                        content=ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            f"#{batch_id} · {name}",
                                            size=13,
                                            weight=ft.FontWeight.W_600,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Text(
                                            f"{item_count} documento(s) · Estado: {status} · {updated_at}",
                                            size=11,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                secondary_button("Ver grupo", lambda e, batch_id=batch_id: open_batch_detail_dialog(batch_id)),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=10,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Grupos documentales", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Container(expand=True),
                            secondary_button("Refrescar grupos", refresh_batches_panel),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    batches_panel_message,
                    ft.Column(controls=rows, spacing=6),
                ],
                spacing=8,
            ),
        )

    def refresh_batches_panel(e=None):
        batches_panel_box.content = build_batches_panel_content()
        try:
            batches_panel_box.update()
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass


    batch_detail_body = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    batch_detail_message = ft.Container()

    def show_batch_item_preview(item):
        file_path = item.get("stored_path") or item.get("linked_document_path") or ""
        if not file_path:
            batch_detail_message.content = error_alert("El documento no tiene ruta interna disponible.")
            try:
                batch_detail_message.update()
            except Exception:
                pass
            return

        try:
            open_document_viewer_modal(
                page,
                file_path,
                title=item.get("original_filename") or item.get("stored_filename") or "Documento del grupo",
            )
        except Exception as exc:
            batch_detail_message.content = error_alert(f"No se pudo abrir el visor: {exc}")
            try:
                batch_detail_message.update()
            except Exception:
                pass

    def open_batch_item_external(item):
        file_path = item.get("stored_path") or item.get("linked_document_path") or ""
        if not file_path:
            batch_detail_message.content = error_alert("El documento no tiene ruta interna disponible.")
            try:
                batch_detail_message.update()
            except Exception:
                pass
            return

        try:
            document_viewer_service.open_document(file_path)
        except TypeError:
            try:
                document_viewer_service.open_document(file_path, expediente_id=item.get("expedient_id"))
            except Exception as exc:
                batch_detail_message.content = error_alert(f"No se pudo abrir externamente: {exc}")
                try:
                    batch_detail_message.update()
                except Exception:
                    pass
        except Exception as exc:
            batch_detail_message.content = error_alert(f"No se pudo abrir externamente: {exc}")
            try:
                batch_detail_message.update()
            except Exception:
                pass

    def close_batch_detail_dialog(e=None):
        batch_detail_dialog.open = False
        try:
            page.update()
        except Exception:
            pass

    def open_batch_detail_dialog(batch_id):
        batch_detail_message.content = None

        try:
            batch = document_inbox_service.get_document_inbox_batch(int(batch_id))
            rows = [
                ft.Text(
                    f"#{batch.get('id')} · {batch.get('name')}",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                ),
                ft.Text(
                    f"Estado: {batch.get('status') or 'draft'} · Documentos: {batch.get('item_count') or 0}",
                    size=12,
                    color=Q_MUTED,
                ),
            ]

            notes = str(batch.get("notes") or "").strip()
            if notes:
                rows.append(ft.Text(notes, size=12, color=Q_MUTED, selectable=True))

            rows.append(ft.Divider())
            rows.append(ft.Text("Documentos del grupo", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK))

            for item in batch.get("items") or []:
                rows.append(
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=10,
                        padding=8,
                        content=ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            f"#{item.get('id')} · {item.get('original_filename') or '-'}",
                                            size=12,
                                            weight=ft.FontWeight.W_600,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Text(
                                            f"Estado: {item.get('status') or '-'} · Origen: {item.get('source_type') or '-'}",
                                            size=10,
                                            color=Q_MUTED,
                                        ),
                                        ft.Text(
                                            item.get("stored_path") or "",
                                            size=10,
                                            color=Q_MUTED,
                                            selectable=True,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                secondary_button("Ver", lambda e, item=item: show_batch_item_preview(item)),
                                secondary_button("Abrir externo", lambda e, item=item: open_batch_item_external(item)),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

            batch_detail_body.controls = rows

        except Exception as exc:
            batch_detail_body.controls = [
                error_alert(f"No se pudo abrir el grupo documental: {exc}")
            ]

        if batch_detail_dialog not in page.overlay:
            page.overlay.append(batch_detail_dialog)

        batch_detail_dialog.open = True
        page.update()

    batch_detail_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Grupo documental", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
        content=ft.Container(
            width=840,
            height=680,
            content=ft.Column(
                controls=[
                    batch_detail_message,
                    batch_detail_body,
                ],
                spacing=8,
                expand=True,
            ),
        ),
        actions=[
            secondary_button("Cerrar", close_batch_detail_dialog),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    batches_panel_box = ft.Container(content=build_batches_panel_content())

    watch_panel_message = ft.Container()
    watch_scan_result_box = ft.Column(spacing=6)

    def _watch_result_rows(result):
        rows = []

        imported = result.get("imported") or []
        skipped = result.get("skipped") or []
        errors = result.get("errors") or []

        rows.append(
            ft.Text(
                f"Importados: {len(imported)} · Saltados: {len(skipped)} · Errores: {len(errors)}",
                size=12,
                weight=ft.FontWeight.BOLD,
                color=Q_PRIMARY_DARK,
            )
        )

        for item in imported[:20]:
            rows.append(
                ft.Text(
                    f"IMPORTADO · {item.get('file_name')} → item #{item.get('inbox_item_id')}",
                    size=11,
                    color=Q_PRIMARY_DARK,
                )
            )

        for item in skipped[:10]:
            rows.append(
                ft.Text(
                    f"SALTADO · {item.get('file_path')} · {item.get('reason')}",
                    size=10,
                    color=Q_MUTED,
                    selectable=True,
                )
            )

        for error in errors[:10]:
            rows.append(
                ft.Text(
                    f"ERROR · {error}",
                    size=10,
                    color="#B42318",
                    selectable=True,
                )
            )

        return rows

    def scan_watch_folder_from_ui(watch_folder_id):
        try:
            result = document_inbox_watch_service.scan_watch_folder(int(watch_folder_id), max_files=100)
            watch_panel_message.content = success_alert(
                f"Escaneo finalizado. Importados: {len(result.get('imported') or [])}. "
                f"Saltados: {len(result.get('skipped') or [])}. "
                f"Errores: {len(result.get('errors') or [])}."
            )
            watch_scan_result_box.controls = _watch_result_rows(result)
            refresh_items()
        except Exception as exc:
            watch_panel_message.content = error_alert(f"No se pudo escanear la carpeta: {exc}")

        refresh_watch_panel()

    def ensure_downloads_watch_from_ui(e=None):
        try:
            folder = document_inbox_watch_service.ensure_default_downloads_watch_folder()
            watch_panel_message.content = success_alert(
                f"Vigilancia de Descargas activada: {folder.get('folder_path')}"
            )
        except Exception as exc:
            watch_panel_message.content = error_alert(f"No se pudo activar Descargas: {exc}")

        refresh_watch_panel()

    def build_watch_panel_content():
        try:
            folders = document_inbox_watch_service.list_watch_folders(active_only=False)
        except Exception as exc:
            return ft.Container(
                bgcolor="#FFFFFF",
                border=ft.border.all(1, Q_BORDER),
                border_radius=14,
                padding=10,
                content=ft.Column(
                    controls=[
                        ft.Text("Vigilancia", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                        error_alert(f"No se pudieron cargar carpetas vigiladas: {exc}"),
                    ],
                    spacing=8,
                ),
            )

        rows = []

        if not folders:
            rows.append(empty_state("Todavía no hay carpetas vigiladas"))
        else:
            for folder in folders:
                folder_id = folder.get("id")
                name = folder.get("name") or "Carpeta vigilada"
                folder_path = folder.get("folder_path") or ""
                is_active = bool(int(folder.get("is_active") or 0))
                recursive = bool(int(folder.get("recursive") or 0))

                rows.append(
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=10,
                        content=ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(
                                            f"#{folder_id} · {name}",
                                            size=13,
                                            weight=ft.FontWeight.W_600,
                                            color=Q_PRIMARY_DARK,
                                        ),
                                        ft.Text(
                                            folder_path,
                                            size=10,
                                            color=Q_MUTED,
                                            selectable=True,
                                        ),
                                        ft.Text(
                                            f"Activa: {'sí' if is_active else 'no'} · Recursiva: {'sí' if recursive else 'no'}",
                                            size=10,
                                            color=Q_MUTED,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                primary_button("Escanear ahora", lambda e, folder_id=folder_id: scan_watch_folder_from_ui(folder_id)),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=10,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Vigilancia de carpetas", size=16, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Container(expand=True),
                            secondary_button("Activar Descargas", ensure_downloads_watch_from_ui),
                            secondary_button("Refrescar", lambda e: refresh_watch_panel()),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "Escanea carpetas locales y copia archivos nuevos a Bandeja Documental. No mueve ni borra los originales.",
                        size=12,
                        color=Q_MUTED,
                    ),
                    watch_panel_message,
                    ft.Column(controls=rows, spacing=6),
                    ft.Divider(),
                    ft.Text("Último resultado", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    watch_scan_result_box,
                ],
                spacing=8,
            ),
        )

    def refresh_watch_panel(e=None):
        watch_panel_box.content = build_watch_panel_content()
        try:
            watch_panel_box.update()
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    watch_panel_box = ft.Container(content=build_watch_panel_content())


    documents_list_box = ft.Container(
                    expand=True,
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=14,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            status_counters_box,
                            ft.Row(
                                controls=[
                                    ft.Text("Documentos", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                    ft.Container(expand=True),
                                    ft.Text("Click en fila para seleccionar. Botón Ficha para abrir detalle.", size=11, color=Q_MUTED),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Container(
                                expand=True,
                                content=items_column,
                            ),
                        ],
                        spacing=10,
                        expand=True,
                    ),
                )

    inbox_tab_state = {"active": "documents"}

    def build_inbox_tab_selector():
        active = inbox_tab_state.get("active") or "documents"

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=8,
            content=ft.Row(
                controls=[
                    primary_button("Documentos", lambda e: set_inbox_tab("documents")) if active == "documents" else secondary_button("Documentos", lambda e: set_inbox_tab("documents")),
                    primary_button("Grupos documentales", lambda e: set_inbox_tab("batches")) if active == "batches" else secondary_button("Grupos documentales", lambda e: set_inbox_tab("batches")),
                    primary_button("Vigilancia", lambda e: set_inbox_tab("watch")) if active == "watch" else secondary_button("Vigilancia", lambda e: set_inbox_tab("watch")),
                    ft.Container(expand=True),
                ],
                spacing=8,
            ),
        )

    def build_active_tab_controls():
        active = inbox_tab_state.get("active") or "documents"

        if active == "batches":
            return [
                batches_panel_box,
            ]

        if active == "watch":
            return [
                watch_panel_box,
            ]

        return [
            bulk_actions_box,
            documents_list_box,
        ]

    def set_inbox_tab(tab_name):
        inbox_tab_state["active"] = tab_name or "documents"

        if inbox_tab_state["active"] == "batches":
            try:
                batches_panel_box.content = build_batches_panel_content()
            except Exception:
                pass

        if inbox_tab_state["active"] == "watch":
            try:
                watch_panel_box.content = build_watch_panel_content()
            except Exception:
                pass

        tab_selector_box.content = build_inbox_tab_selector()
        tab_content_box.controls = build_active_tab_controls()

        try:
            tab_selector_box.update()
        except Exception:
            pass
        try:
            tab_content_box.update()
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    tab_selector_box = ft.Container(content=build_inbox_tab_selector())
    tab_content_box = ft.Column(controls=build_active_tab_controls(), spacing=10, expand=True)



    batch_name_field = text_input("Nombre del grupo documental", width=680)
    batch_notes_field = multiline_input("Notas del grupo", width=680)
    batch_dialog_message = ft.Container()
    batch_selected_docs_box = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)

    def close_create_batch_dialog(e=None):
        create_batch_dialog.open = False
        try:
            page.update()
        except Exception:
            pass

    def render_batch_selected_docs():
        selected_ids = list(state.get("selected_item_ids") or [])
        rows = []

        if not selected_ids:
            rows.append(empty_state("No hay documentos seleccionados"))
        else:
            selected_set = set(int(x) for x in selected_ids)
            items = document_inbox_service.list_inbox_items(status=None, limit=1000)
            selected_items = [item for item in items if int(item.get("id")) in selected_set]

            for item in selected_items:
                rows.append(
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=10,
                        padding=8,
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    f"#{item.get('id')} · {item.get('original_filename') or '-'}",
                                    size=12,
                                    weight=ft.FontWeight.W_600,
                                    color=Q_PRIMARY_DARK,
                                ),
                                ft.Text(
                                    f"Origen: {item.get('source_type') or '-'} · Estado: {item.get('status') or '-'}",
                                    size=10,
                                    color=Q_MUTED,
                                ),
                            ],
                            spacing=2,
                        ),
                    )
                )

        batch_selected_docs_box.controls = rows

    def open_create_batch_dialog(e=None):
        selected_ids = list(state.get("selected_item_ids") or [])

        batch_dialog_message.content = None
        batch_name_field.value = ""
        batch_notes_field.value = ""

        if selected_ids:
            batch_name_field.value = f"Grupo documental ({len(selected_ids)} documentos)"

        render_batch_selected_docs()

        if create_batch_dialog not in page.overlay:
            page.overlay.append(create_batch_dialog)

        create_batch_dialog.open = True
        page.update()

    def create_batch_from_selection(e=None):
        selected_ids = list(state.get("selected_item_ids") or [])

        if not selected_ids:
            batch_dialog_message.content = error_alert("Selecciona al menos un documento para crear el grupo.")
            try:
                batch_dialog_message.update()
            except Exception:
                pass
            return

        name = (batch_name_field.value or "").strip()
        if not name:
            batch_dialog_message.content = error_alert("Indica un nombre para el grupo documental.")
            try:
                batch_dialog_message.update()
            except Exception:
                pass
            return

        try:
            batch = document_inbox_service.create_document_inbox_batch(
                name=name,
                inbox_item_ids=selected_ids,
                notes=batch_notes_field.value or "",
            )

            state["selected_item_ids"] = set()
            selected_label.value = "Ningún documento seleccionado."
            bulk_actions_box.content = build_bulk_actions_content()
            render_items()

            batch_dialog_message.content = success_alert(
                f"Grupo #{batch.get('id')} creado con {batch.get('item_count')} documento(s)."
            )

            try:
                selected_label.update()
            except Exception:
                pass
            try:
                bulk_actions_box.update()
            except Exception:
                pass
            try:
                items_column.update()
            except Exception:
                pass
            try:
                batch_dialog_message.update()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass

        except Exception as exc:
            batch_dialog_message.content = error_alert(f"No se pudo crear el grupo: {exc}")
            try:
                batch_dialog_message.update()
            except Exception:
                pass

    create_batch_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Agrupar documentos", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
        content=ft.Container(
            width=780,
            height=620,
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Crea un grupo documental interno con los documentos seleccionados. No se mueve nada en Box.",
                        size=12,
                        color=Q_MUTED,
                    ),
                    batch_dialog_message,
                    batch_name_field,
                    batch_notes_field,
                    ft.Text("Documentos incluidos", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Container(
                        expand=True,
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=8,
                        content=batch_selected_docs_box,
                    ),
                ],
                spacing=10,
                expand=True,
            ),
        ),
        actions=[
            secondary_button("Cerrar", close_create_batch_dialog),
            primary_button("Crear grupo", create_batch_from_selection),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    return ft.Container(
        expand=True,
        bgcolor="#F8FAFC",
        padding=16,
        content=ft.Column(
            controls=[
                header,
                message_box,
                ft.Row(
                    controls=[
                        primary_button("Importar a bandeja", open_import_dialog),
                        secondary_button("Actualizar", refresh_items),
                        ft.Container(expand=True),
                        selected_label,
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                tab_selector_box,
                tab_content_box,
            ],
            spacing=12,
            expand=True,
        ),
    )

