import json

import flet as ft

from backend.services import document_inbox_service
from backend.services.list_expediente_box_directory import list_expediente_box_directory
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
    "duplicate": "Duplicados",
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
        "duplicate": ("#FEF0C7", "#B54708"),
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
        "page": 1,
        "page_size": 10,
        "total_items": 0,
        "last_watch_scan": None,
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
    pagination_label = ft.Text("Página 1", color=Q_MUTED, size=12)
    watch_scan_notice = ft.Text("", color=Q_MUTED, size=12)
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
            raw_counts = document_inbox_service.count_inbox_items_by_status()
        except Exception:
            raw_counts = {}

        counts = {key: int(raw_counts.get(key, 0) or 0) for key in status_keys}
        total = int(raw_counts.get("all", sum(counts.values())) or 0)

        current = status_dropdown.value or state.get("status_filter") or "all"

        def set_status_filter(status_value):
            state["status_filter"] = status_value
            state["page"] = 1
            state["selected_item_ids"] = set()
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

    def document_total_pages():
        total = int(state.get("total_items") or 0)
        page_size = max(1, int(state.get("page_size") or 10))
        return max(1, (total + page_size - 1) // page_size)

    def refresh_pagination_label():
        total = int(state.get("total_items") or 0)
        page_size = max(1, int(state.get("page_size") or 10))
        page_number = max(1, int(state.get("page") or 1))
        pages = document_total_pages()

        start_index = 0 if total == 0 else ((page_number - 1) * page_size) + 1
        end_index = min(total, page_number * page_size)

        pagination_label.value = f"Mostrando {start_index}-{end_index} de {total} · Página {page_number} de {pages}"

        try:
            pagination_label.update()
        except Exception:
            pass

    def go_document_page(page_number):
        state["page"] = max(1, min(int(page_number or 1), document_total_pages()))
        state["selected_item_ids"] = set()
        refresh_items()

    def previous_document_page(e=None):
        go_document_page(int(state.get("page") or 1) - 1)

    def next_document_page(e=None):
        go_document_page(int(state.get("page") or 1) + 1)

    def on_status_filter_change(e=None):
        state["page"] = 1
        state["selected_item_ids"] = set()
        refresh_items(e)


    def refresh_watch_scan_notice():
        result = state.get("last_watch_scan") or {}

        folders = result.get("folders") or []
        imported = int(result.get("imported") or 0)
        skipped = int(result.get("skipped") or 0)
        errors = int(result.get("errors") or 0)

        if not folders:
            watch_scan_notice.value = "Vigilancia: sin carpetas activas"
            watch_scan_notice.color = Q_MUTED
        elif errors:
            watch_scan_notice.value = f"Vigilancia: {imported} nuevos · {skipped} ya vistos · {errors} errores"
            watch_scan_notice.color = "#B91C1C"
        elif imported:
            watch_scan_notice.value = f"Vigilancia: {imported} nuevos · {skipped} ya vistos · 0 errores"
            watch_scan_notice.color = "#166534"
        else:
            watch_scan_notice.value = f"Vigilancia: 0 nuevos · {skipped} ya vistos · 0 errores"
            watch_scan_notice.color = Q_MUTED

        try:
            watch_scan_notice.update()
        except Exception:
            pass


    def scan_watch_folders_for_inbox():
        """
        Escaneo incremental de carpetas vigiladas.

        Se llama solo:
        - al abrir Bandeja
        - al pulsar Actualizar

        No se llama al paginar ni al cambiar filtros.
        """
        try:
            result = document_inbox_watch_service.scan_active_watch_folders(max_files_per_folder=200)
        except Exception as exc:
            result = {
                "folders": [],
                "results": [],
                "imported": 0,
                "skipped": 0,
                "errors": 1,
                "error_message": str(exc),
            }

        state["last_watch_scan"] = result

        try:
            refresh_watch_scan_notice()
        except Exception:
            pass

        return result


    def refresh_items(e=None, scan_watch=False):
        if scan_watch:
            scan_watch_folders_for_inbox()

        query_status = status_dropdown.value
        if query_status == "all":
            query_status = None

        page_size = max(1, int(state.get("page_size") or 10))
        total = document_inbox_service.count_inbox_items(status=query_status)

        pages = max(1, (int(total or 0) + page_size - 1) // page_size)
        page_number = max(1, min(int(state.get("page") or 1), pages))
        offset = (page_number - 1) * page_size

        state["page"] = page_number
        state["total_items"] = int(total or 0)
        state["items"] = document_inbox_service.list_inbox_items(
            status=query_status,
            limit=page_size,
            offset=offset,
        )

        visible_ids = {int(item.get("id")) for item in state["items"] if item.get("id") is not None}
        state["selected_item_ids"] = {
            int(item_id)
            for item_id in state.get("selected_item_ids", set())
            if int(item_id) in visible_ids
        }

        try:
            update_status_counters()
        except NameError:
            pass

        try:
            status_counters_box.content = build_status_counters()
            status_counters_box.update()
        except Exception:
            pass

        render_items()
        refresh_pagination_label()

        try:
            page.update()
        except Exception:
            pass

        selected_label.value = "Seleccionado: ninguno"
        try:
            selected_label.update()
        except Exception:
            pass
        try:
            items_column.update()
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

    def _normalize_box_subfolder_for_copy(selected_directory: str = "", base_box_folder: str = "") -> str:
        raw = str(selected_directory or "").strip()
        base = str(base_box_folder or "").strip()

        if not raw:
            return ""

        try:
            from pathlib import Path as _Path
            raw_path = _Path(raw).expanduser()
            base_path = _Path(base).expanduser() if base else None

            if base_path and raw_path.is_absolute():
                try:
                    return str(raw_path.relative_to(base_path)).replace("\\", "/").strip("/")
                except ValueError:
                    pass
        except Exception:
            pass

        return raw.replace("\\", "/").strip("/")


    def _resolve_box_subfolder_for_copy() -> str:
        override = state.pop("copy_to_box_subfolder_override", None)
        if override is not None:
            return str(override or "").strip()
        return str(box_subfolder.value or "").strip()


    def copy_to_box(e=None):
        try:
            item = selected_item()
            eid = state.get("selected_expedient_id") or item.get("expedient_id")
            if not eid:
                raise ValueError("Selecciona un expediente antes de copiar a Box.")

            updated = document_inbox_service.copy_inbox_item_to_expedient_box(
                item["id"],
                expedient_id=int(eid),
                subfolder=_resolve_box_subfolder_for_copy(),
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

    def mark_detected_duplicates(e=None):
        try:
            result = document_inbox_service.mark_detected_inbox_duplicates(
                status_filter=state.get("status_filter"),
            )
            show_success(
                f"Duplicados marcados: {result.get('marked_count', 0)} · "
                f"Omitidos: {result.get('skipped_count', 0)} · "
                f"Errores: {result.get('error_count', 0)}"
            )
            refresh_items()
        except Exception as exc:
            show_error(exc)

    def open_principal_from_duplicate(duplicate_of_id):
        try:
            principal_id = int(duplicate_of_id or 0)
            if not principal_id:
                raise ValueError("Este duplicado no tiene documento principal asociado.")

            state["selected_item_id"] = principal_id
            state["selected_item_ids"] = set()
            open_document_detail_dialog()
        except Exception as exc:
            show_error(exc)

    def render_items():
        selected_ids = set(state.get("selected_item_ids") or set())
        rows = []

        for item in state.get("items", []):
            item_id = int(item.get("id"))
            selected = item_id in selected_ids

            is_duplicate = bool(item.get("is_duplicate"))
            duplicate_label = ""
            if is_duplicate:
                duplicate_label = (
                    f"Duplicado de #{item.get('duplicate_of_id') or '-'}"
                    f" · {item.get('duplicate_reason') or 'posible duplicado'}"
                )

            rows.append(
                ft.Container(
                    padding=10,
                    border_radius=12,
                    border=ft.border.all(
                        2 if selected else 1,
                        "#F79009" if is_duplicate else (Q_PRIMARY if selected else Q_BORDER),
                    ),
                    bgcolor="#FFF7E6" if is_duplicate else ("#EFF8FF" if selected else "#FFFFFF"),
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
                                            ft.Container(
                                                visible=is_duplicate,
                                                padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                                border_radius=999,
                                                bgcolor="#FEF0C7",
                                                content=ft.Text(
                                                    duplicate_label,
                                                    size=11,
                                                    color="#B54708",
                                                    weight=ft.FontWeight.BOLD,
                                                ),
                                            ),
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

    status_dropdown.on_change = on_status_filter_change

    header = ft.Row(
        controls=[
            ft.Text("Bandeja documental", size=26, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            ft.Container(expand=True),
            status_dropdown,
            secondary_button("Actualizar", refresh_items),
            secondary_button("Marcar duplicados detectados", mark_detected_duplicates),
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
                        secondary_button("Duplicado", lambda e: set_status("duplicate")),
                        danger_button("Descartar", lambda e: set_status("discarded")),
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ],
            spacing=10,
        ),
    )

    refresh_items(scan_watch=True)

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
        """
        Ficha documental aislada.

        No reutiliza controles de la Bandeja principal para evitar glitches de Flet
        cuando un mismo control aparece en varios contenedores/dialogs.
        """
        try:
            active_item_id = state.get("selected_item_id")
            if active_item_id:
                item = document_inbox_service.get_inbox_item(int(active_item_id))
            else:
                item = selected_item()
        except Exception as exc:
            show_error(exc)
            return

        item_id = int(item.get("id"))
        filename = item.get("original_filename") or "-"
        stored_path = item.get("stored_path") or "-"
        status = item.get("status") or "pending"
        is_duplicate = bool(item.get("is_duplicate"))
        duplicate_of_id = item.get("duplicate_of_id")
        duplicate_reason = item.get("duplicate_reason") or ""

        def _clean_visible_label(label):
            """
            Limpia labels técnicos:
            - #25 <sep> NOMBRE <sep> DOC
            - 25 - NOMBRE
            - 25 · NOMBRE
            - 25 | NOMBRE
            """
            label = str(label or "").strip()
            if not label:
                return ""

            weird_sep = chr(0x2592)

            if weird_sep in label:
                parts = [p.strip() for p in label.split(weird_sep) if p.strip()]
                if len(parts) >= 2:
                    first = parts[0].strip().lstrip("#").strip()
                    if first.isdigit():
                        return parts[1].strip()

            for sep in [" - ", " · ", " | "]:
                if sep in label:
                    left, right = label.split(sep, 1)
                    left = left.strip().lstrip("#").strip()
                    if left.isdigit() and right.strip():
                        return right.strip()

            return label

        def _option_visible_label(option, fallback_keys=None):
            fallback_keys = fallback_keys or []

            if isinstance(option, dict):
                for key in fallback_keys:
                    value = str(option.get(key) or "").strip()
                    if value:
                        return _clean_visible_label(value)

                value = str(option.get("label") or option.get("name") or option.get("value") or "").strip()
                return _clean_visible_label(value)

            return _clean_visible_label(option)

        def _client_visible_label(option):
            if isinstance(option, dict):
                client = option.get("client") or {}
                nombre = " ".join(
                    str(client.get(key) or "").strip()
                    for key in ["nombre", "primer_apellido", "segundo_apellido"]
                    if str(client.get(key) or "").strip()
                ).strip()

                if nombre:
                    return nombre

            return _option_visible_label(option)

        def _type_from_box_folder_path(box_folder_path):
            """
            Extrae el tipo principal desde la ruta Box del expediente.
            Ejemplo:
            NUEVO REGLAMENTO / REAGRUPACION FAMILIAR / 2026 / CLIENTE
            """
            raw = str(box_folder_path or "").strip()
            if not raw:
                return ""

            parts = [p.strip() for p in raw.replace("/", "\\").split("\\") if p.strip()]
            if not parts:
                return ""

            for i, part in enumerate(parts):
                if part.upper() == "NUEVO REGLAMENTO" and i + 1 < len(parts):
                    return parts[i + 1].strip()

            for i, part in enumerate(parts):
                if part.isdigit() and len(part) == 4 and i - 1 >= 0:
                    candidate = parts[i - 1].strip()
                    if candidate.upper() not in {"BOX", "USERS", "NACHO"}:
                        return candidate

            return ""


        def _expedient_visible_label(option):
            """
            Mostrar SOLO el tipo principal del expediente.
            Prioridad:
            1) campo tipo si viene enriquecido
            2) inferir desde box_folder_path
            3) fallback por ID
            """
            expedient = {}
            expedient_id = None

            if isinstance(option, dict):
                expedient = option.get("expedient") or {}
                expedient_id = option.get("id") or option.get("value") or expedient.get("id")

            if expedient_id:
                try:
                    full = document_inbox_service.get_expedient(int(expedient_id)) or {}
                    if isinstance(full, dict):
                        enriched = dict(expedient)
                        enriched.update(full)
                        expedient = enriched
                except Exception:
                    pass

            for key in [
                "tipo_expediente",
                "nombre_tipo_expediente",
                "tipo_expediente_nombre",
                "tipo_nombre",
                "tipo",
            ]:
                value = str((expedient or {}).get(key) or "").strip()
                if value:
                    return value

            inferred = _type_from_box_folder_path((expedient or {}).get("box_folder_path"))
            if inferred:
                return inferred

            tipo_id = str((expedient or {}).get("tipo_expediente_id") or "").strip()
            if tipo_id:
                return f"Tipo expediente ID {tipo_id}"

            return _option_visible_label(option)


        detail_events_box = ft.Container(content=build_events_panel())

        detail_relation_text = ft.Text(
            f"Cliente ID: {item.get('client_id') or '-'} · Expediente ID: {item.get('expedient_id') or '-'}",
            size=12,
            color=Q_MUTED,
        )

        def detail_show_preview(e=None):
            try:
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

        def detail_open_system(e=None):
            try:
                document_viewer_service.open_document(item.get("stored_path"))
            except Exception as exc:
                show_error(exc)

        def detail_open_principal(e=None):
            try:
                principal_id = int(duplicate_of_id or 0)
                if not principal_id:
                    raise ValueError("Este duplicado no tiene documento principal asociado.")

                dialog = state.get("document_detail_dialog")
                if dialog:
                    dialog.open = False

                state["selected_item_id"] = principal_id
                state["selected_item_ids"] = set()

                refresh_items()
                open_document_detail_dialog()
            except Exception as exc:
                show_error(exc)

        def detail_link_selected(e=None):
            try:
                state["selected_item_id"] = item_id

                detail_client_id = state.get("detail_selected_client_id")
                detail_expedient_id = state.get("detail_selected_expedient_id")

                if detail_client_id:
                    state["selected_client_id"] = int(detail_client_id)

                if detail_expedient_id:
                    state["selected_expedient_id"] = int(detail_expedient_id)

                link_selected(e)

                refreshed = document_inbox_service.get_inbox_item(item_id)
                detail_relation_text.value = (
                    f"Cliente ID: {refreshed.get('client_id') or '-'} · "
                    f"Expediente ID: {refreshed.get('expedient_id') or '-'}"
                )
                try:
                    detail_relation_text.update()
                except Exception:
                    pass
            except Exception as exc:
                show_error(exc)

        def detail_copy_to_box(e=None):
            try:
                state["selected_item_id"] = item_id

                detail_client_id = state.get("detail_selected_client_id")
                detail_expedient_id = state.get("detail_selected_expedient_id")

                if detail_client_id:
                    state["selected_client_id"] = int(detail_client_id)

                if detail_expedient_id:
                    state["selected_expedient_id"] = int(detail_expedient_id)

                selected_directory = state.get("detail_selected_directory")
                base_box_folder = state.get("detail_selected_expedient_box_folder_path")
                state["copy_to_box_subfolder_override"] = _normalize_box_subfolder_for_copy(
                    selected_directory,
                    base_box_folder,
                )

                copy_to_box(e)

                refreshed = document_inbox_service.get_inbox_item(item_id)
                detail_relation_text.value = (
                    f"Cliente ID: {refreshed.get('client_id') or '-'} · "
                    f"Expediente ID: {refreshed.get('expedient_id') or '-'} · "
                    f"Estado: {refreshed.get('status') or '-'} · "
                    f"Box destino: {refreshed.get('copied_to_box_path') or '-'}"
                )
                detail_events_box.content = build_events_panel()

                try:
                    detail_relation_text.update()
                except Exception:
                    pass

                try:
                    detail_events_box.update()
                except Exception:
                    pass
            except Exception as exc:
                show_error(exc)

        def detail_mark_reviewed(e=None):
            try:
                updated = document_inbox_service.update_inbox_item_status(item_id, "reviewed")
                show_success(f"Documento #{updated['id']} marcado como revisado.")
                refresh_items()
                close_document_detail_dialog()
            except Exception as exc:
                show_error(exc)

        def detail_discard(e=None):
            try:
                updated = document_inbox_service.update_inbox_item_status(item_id, "discarded")
                show_success(f"Documento #{updated['id']} descartado.")
                refresh_items()
                close_document_detail_dialog()
            except Exception as exc:
                show_error(exc)

        detail_header = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("📄", size=24),
                            ft.Column(
                                controls=[
                                    ft.Text(f"Documento #{item_id}", size=12, color=Q_MUTED),
                                    ft.Text(filename, size=18, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                ],
                                spacing=2,
                                expand=True,
                            ),
                            _status_chip(status),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    ft.Text(stored_path, size=11, color=Q_MUTED, selectable=True),
                ],
                spacing=8,
            ),
        )

        detail_duplicate = ft.Container(
            visible=is_duplicate,
            bgcolor="#FFF7E6",
            border=ft.border.all(1, "#F79009"),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text("Documento duplicado", size=15, weight=ft.FontWeight.BOLD, color="#B54708"),
                    ft.Text(
                        f"Este documento está marcado como duplicado de #{duplicate_of_id or '-'}"
                        f" · {duplicate_reason or 'sin motivo'}",
                        size=12,
                        color="#B54708",
                    ),
                    ft.Row(
                        controls=[
                            secondary_button("Abrir principal", detail_open_principal),
                        ],
                        spacing=10,
                    ),
                ],
                spacing=8,
            ),
        )

        detail_meta = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text("Metadatos", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(
                        f"Origen: {item.get('source_type') or '-'} · {item.get('source_label') or '-'}",
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        f"Tamaño: {_format_size(item.get('size_bytes'))} · Creado: {item.get('created_at') or '-'}",
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Text(
                        f"Box destino: {item.get('copied_to_box_path') or '-'}",
                        size=12,
                        color=Q_MUTED,
                        selectable=True,
                    ),
                ],
                spacing=6,
            ),
        )

        detail_relation = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text("Relación", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    detail_relation_text,
                    ft.Text(
                        "Para cambiar cliente/expediente usa el panel de acciones de la Bandeja principal.",
                        size=11,
                        color=Q_MUTED,
                    ),
                ],
                spacing=6,
            ),
        )

        detail_actions = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text("Acciones rápidas", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row(
                        controls=[
                            primary_button("Ver", detail_show_preview),
                            secondary_button("Abrir original", detail_open_system),
                            secondary_button("Revisado", detail_mark_reviewed),
                            danger_button("Descartar", detail_discard),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                spacing=8,
            ),
        )

        detail_trace = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text("Trazabilidad", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    detail_events_box,
                ],
                spacing=8,
            ),
        )

        detail_pdf_tools = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text("Herramientas PDF", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(
                        "Zona preparada para aplicar operaciones al documento actual.",
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Row(
                        controls=[
                            primary_button("Ver PDF", detail_show_preview),
                            secondary_button("Abrir original", detail_open_system),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(height=12),
                    ft.Text("Próximas acciones", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row(
                        controls=[
                            secondary_button("Renombrar", lambda e: show_error("Pendiente: renombrar documento.")),
                            secondary_button("Separar páginas", lambda e: show_error("Pendiente: separar PDF.")),
                            secondary_button("Unir con selección", lambda e: show_error("Pendiente: unir PDFs seleccionados.")),
                            secondary_button("OCR / texto", lambda e: show_error("Pendiente: OCR / extracción de texto.")),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                spacing=10,
            ),
        )

        detail_client_label = ft.Text(
            f"Cliente seleccionado: {state.get('detail_selected_client_id') or state.get('selected_client_id') or '-'}",
            size=12,
            color=Q_MUTED,
        )

        detail_expedient_label = ft.Text(
            f"Expediente seleccionado: {state.get('detail_selected_expedient_id') or state.get('selected_expedient_id') or '-'}",
            size=12,
            color=Q_MUTED,
        )

        detail_directory_label = ft.Text(
            f"Directorio seleccionado: {state.get('detail_selected_directory') or '-'}",
            size=12,
            color=Q_MUTED,
        )

        detail_directory_label_to_path = {}

        def build_directory_options_for_expedient(expedient_id):
            detail_directory_label_to_path.clear()

            base_path = str(state.get("detail_selected_expedient_box_folder_path") or "").strip()

            if not base_path and expedient_id:
                try:
                    expedient = document_inbox_service.get_expedient(int(expedient_id)) or {}
                    base_path = str(expedient.get("box_folder_path") or "").strip()
                except Exception:
                    base_path = ""

            if not base_path:
                return []

            try:
                data = list_expediente_box_directory(base_path, relative_base=base_path)
            except Exception as exc:
                show_error(f"No se pudieron listar directorios del expediente: {exc}")
                return []

            labels = []
            seen = set()

            def add_folder(label, path_value):
                label = str(label or "").strip()
                path_value = str(path_value or label or "").strip()
                if not label or label in seen:
                    return
                seen.add(label)
                labels.append(label)
                detail_directory_label_to_path[label] = path_value

            # Estructura real comprobada:
            # {"folders": [{"name": "...", "path": "...", "relative_path": "..."}], "files": [...]}
            if isinstance(data, dict):
                for folder in data.get("folders") or []:
                    if not isinstance(folder, dict):
                        continue

                    label = str(folder.get("relative_path") or folder.get("name") or "").strip()
                    folder_path = str(folder.get("path") or folder.get("absolute_path") or label).strip()

                    add_folder(label, folder_path)

            # Fallback por si en otro caso llega una lista directa.
            elif isinstance(data, list):
                for folder in data:
                    if isinstance(folder, dict):
                        label = str(folder.get("relative_path") or folder.get("name") or "").strip()
                        folder_path = str(folder.get("path") or folder.get("absolute_path") or label).strip()
                        add_folder(label, folder_path)

            return labels


        def on_detail_directory_selected(value):
            try:
                label = _normalize_autocomplete_value(value)
                if not label:
                    return

                state["detail_selected_directory"] = detail_directory_label_to_path.get(label) or label
                detail_directory_label.value = f"Directorio seleccionado: {state.get('detail_selected_directory') or '-'}"

                try:
                    detail_directory_label.update()
                except Exception:
                    pass
            except Exception as exc:
                show_error(exc)

        detail_directory_autocomplete = AppAutocomplete(
            page,
            label="Directorio / carpeta destino",
            options=[],
            on_select=on_detail_directory_selected,
        )

        detail_client_options_raw = document_inbox_service.client_autocomplete_options()
        detail_client_labels = []
        detail_client_label_to_id = {}

        for option in detail_client_options_raw or []:
            raw_label = ""
            value = None

            if isinstance(option, dict):
                raw_label = str(option.get("label") or option.get("name") or option.get("value") or "").strip()
                label = _client_visible_label(option)
                value = option.get("id") or option.get("value")
            else:
                raw_label = str(option or "").strip()
                label = _clean_visible_label(raw_label)
                value = None

            if not label:
                continue

            visible_label = label
            if visible_label in detail_client_label_to_id:
                visible_label = f"{label} ({value or raw_label})"

            detail_client_labels.append(visible_label)

            try:
                if value is not None:
                    detail_client_label_to_id[visible_label] = int(value)
                elif " - " in raw_label:
                    detail_client_label_to_id[visible_label] = int(raw_label.split(" - ", 1)[0])
            except Exception:
                pass

        detail_expedient_label_to_id = {}

        detail_expedient_label_to_box_path = {}

        def _normalize_autocomplete_value(value):
            if isinstance(value, dict):
                return str(value.get("label") or value.get("value") or value.get("name") or "").strip()
            return str(value or "").strip()

        def _extract_id_from_label(label, mapping):
            label = str(label or "").strip()
            if label in mapping:
                return int(mapping[label])

            if " - " in label:
                try:
                    return int(label.split(" - ", 1)[0])
                except Exception:
                    return None

            return None

        def on_detail_client_selected(value):
            try:
                label = _normalize_autocomplete_value(value)
                client_id = _extract_id_from_label(label, detail_client_label_to_id)

                if not client_id:
                    raise ValueError("No se pudo identificar el cliente seleccionado.")

                state["detail_selected_client_id"] = int(client_id)
                state["selected_client_id"] = int(client_id)

                expedient_options_raw = document_inbox_service.expedient_autocomplete_options_for_client(int(client_id))
                expedient_labels = []
                detail_expedient_label_to_id.clear()
                detail_expedient_label_to_box_path.clear()

                for option in expedient_options_raw or []:
                    raw_exp_label = ""
                    exp_value = None

                    if isinstance(option, dict):
                        raw_exp_label = str(option.get("label") or option.get("name") or option.get("value") or "").strip()
                        exp_label = _expedient_visible_label(option)
                        exp_value = option.get("id") or option.get("value")
                    else:
                        raw_exp_label = str(option or "").strip()
                        exp_label = _clean_visible_label(raw_exp_label)
                        exp_value = None

                    if not exp_label:
                        continue

                    visible_exp_label = exp_label
                    if visible_exp_label in detail_expedient_label_to_id:
                        visible_exp_label = f"{exp_label} ({exp_value or raw_exp_label})"

                    expedient_labels.append(visible_exp_label)

                    try:
                        if exp_value is not None:
                            detail_expedient_label_to_id[visible_exp_label] = int(exp_value)
                        elif " - " in raw_exp_label:
                            detail_expedient_label_to_id[visible_exp_label] = int(raw_exp_label.split(" - ", 1)[0])
                    except Exception:
                        pass

                    try:
                        if isinstance(option, dict):
                            exp_obj = option.get("expedient") or {}
                            box_path = str(exp_obj.get("box_folder_path") or "").strip()
                            if box_path:
                                detail_expedient_label_to_box_path[visible_exp_label] = box_path
                    except Exception:
                        pass

                detail_expedient_autocomplete.set_options(expedient_labels, clear_value=True)

                detail_client_label.value = f"Cliente seleccionado: {label}"
                detail_expedient_label.value = "Expediente seleccionado: -"

                state["detail_selected_expedient_id"] = None
                state["selected_expedient_id"] = None

                try:
                    detail_client_label.update()
                    detail_expedient_label.update()
                except Exception:
                    pass

            except Exception as exc:
                show_error(exc)

        def on_detail_expedient_selected(value):
            try:
                label = _normalize_autocomplete_value(value)
                expedient_id = _extract_id_from_label(label, detail_expedient_label_to_id)

                if not expedient_id:
                    raise ValueError("No se pudo identificar el expediente seleccionado.")

                state["detail_selected_expedient_id"] = int(expedient_id)
                state["selected_expedient_id"] = int(expedient_id)

                selected_box_path = detail_expedient_label_to_box_path.get(label)
                if selected_box_path:
                    state["detail_selected_expedient_box_folder_path"] = selected_box_path

                detail_expedient_label.value = f"Expediente seleccionado: {label}"

                try:
                    directory_labels = build_directory_options_for_expedient(int(expedient_id))
                    detail_directory_autocomplete.set_options(directory_labels, clear_value=True)
                except Exception:
                    pass

                try:
                    detail_expedient_label.update()
                except Exception:
                    pass

            except Exception as exc:
                show_error(exc)

        detail_client_autocomplete = AppAutocomplete(
            page,
            label="Cliente",
            options=detail_client_labels,
            on_select=on_detail_client_selected,
        )

        detail_expedient_autocomplete = AppAutocomplete(
            page,
            label="Expediente",
            options=[],
            on_select=on_detail_expedient_selected,
        )

        initial_client_id = state.get("detail_selected_client_id") or state.get("selected_client_id") or item.get("client_id")
        initial_expedient_id = state.get("detail_selected_expedient_id") or state.get("selected_expedient_id") or item.get("expedient_id")

        if initial_client_id:
            state["detail_selected_client_id"] = int(initial_client_id)
            state["selected_client_id"] = int(initial_client_id)
            detail_client_label.value = "Cliente seleccionado: cargado desde documento/selección"

            try:
                expedient_options_raw = document_inbox_service.expedient_autocomplete_options_for_client(int(initial_client_id))
                expedient_labels = []
                detail_expedient_label_to_id.clear()
                detail_expedient_label_to_box_path.clear()

                for option in expedient_options_raw or []:
                    raw_exp_label = ""
                    exp_value = None

                    if isinstance(option, dict):
                        raw_exp_label = str(option.get("label") or option.get("name") or option.get("value") or "").strip()
                        exp_label = _expedient_visible_label(option)
                        exp_value = option.get("id") or option.get("value")
                    else:
                        raw_exp_label = str(option or "").strip()
                        exp_label = _clean_visible_label(raw_exp_label)
                        exp_value = None

                    if not exp_label:
                        continue

                    visible_exp_label = exp_label
                    if visible_exp_label in detail_expedient_label_to_id:
                        visible_exp_label = f"{exp_label} ({exp_value or raw_exp_label})"

                    expedient_labels.append(visible_exp_label)

                    try:
                        if exp_value is not None:
                            detail_expedient_label_to_id[visible_exp_label] = int(exp_value)
                        elif " - " in raw_exp_label:
                            detail_expedient_label_to_id[visible_exp_label] = int(raw_exp_label.split(" - ", 1)[0])
                    except Exception:
                        pass

                    try:
                        if isinstance(option, dict):
                            exp_obj = option.get("expedient") or {}
                            box_path = str(exp_obj.get("box_folder_path") or "").strip()
                            if box_path:
                                detail_expedient_label_to_box_path[visible_exp_label] = box_path
                    except Exception:
                        pass

                detail_expedient_autocomplete.set_options(expedient_labels, clear_value=True)
            except Exception:
                pass

        if initial_expedient_id:
            state["detail_selected_expedient_id"] = int(initial_expedient_id)
            state["selected_expedient_id"] = int(initial_expedient_id)
            detail_expedient_label.value = "Expediente seleccionado: cargado desde documento/selección"

            try:
                detail_directory_autocomplete.set_options(
                    build_directory_options_for_expedient(int(initial_expedient_id)),
                    clear_value=True,
                )
            except Exception:
                pass

        def detail_save_directory(e=None):
            try:
                show_success("Directorio de destino guardado en la ficha.")
            except Exception as exc:
                show_error(exc)


        detail_linking = ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                controls=[
                    ft.Text("Vincular documento", size=15, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    detail_relation_text,
                    ft.Text(
                        "Selecciona cliente, expediente y, opcionalmente, un directorio destino para este documento.",
                        size=12,
                        color=Q_MUTED,
                    ),
                    ft.Row(
                        controls=[
                            detail_client_autocomplete.control,
                            detail_expedient_autocomplete.control,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Container(
                        bgcolor="#F8FAFC",
                        border=ft.border.all(1, Q_BORDER),
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            controls=[
                                ft.Text("Selección de la ficha", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                                detail_client_label,
                                detail_expedient_label,
                            ],
                            spacing=4,
                        ),
                    ),
                    detail_directory_autocomplete.control,
                    detail_directory_label,
                    ft.Row(
                        controls=[
                            secondary_button("Guardar directorio", detail_save_directory),
                            primary_button("Vincular documento", detail_link_selected),
                            secondary_button("Copiar a Box expediente", detail_copy_to_box),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Divider(height=12),
                    ft.Text("Estado documental", size=13, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Row(
                        controls=[
                            secondary_button("Marcar revisado", detail_mark_reviewed),
                            danger_button("Descartar", detail_discard),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                spacing=10,
            ),
        )

        detail_body = ft.Container(expand=True)

        def set_detail_section(section_name, do_update=True):
            if section_name == "principal":
                detail_body.content = ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Container(content=detail_meta, expand=True),
                                ft.Container(content=detail_relation, expand=True),
                            ],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                        detail_actions,
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                )
            elif section_name == "vincular":
                detail_body.content = ft.Column(
                    controls=[
                        detail_linking,
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                )
            elif section_name == "pdf":
                detail_body.content = ft.Column(
                    controls=[
                        detail_pdf_tools,
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                )
            elif section_name == "trazabilidad":
                detail_body.content = ft.Column(
                    controls=[
                        detail_trace,
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                )
            else:
                detail_body.content = ft.Text("Sección no disponible.", color=Q_MUTED)

            if do_update:
                try:
                    detail_body.update()
                except Exception:
                    pass

        set_detail_section("principal", do_update=False)

        detail_menu = ft.Container(
            bgcolor="#F8FAFC",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=10,
            content=ft.Row(
                controls=[
                    primary_button("Principal", lambda e: set_detail_section("principal")),
                    secondary_button("Vincular", lambda e: set_detail_section("vincular")),
                    secondary_button("Herramientas PDF", lambda e: set_detail_section("pdf")),
                    secondary_button("Trazabilidad", lambda e: set_detail_section("trazabilidad")),
                ],
                spacing=10,
                wrap=True,
            ),
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Ficha documental", size=20, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
            content=ft.Container(
                width=1040,
                height=760,
                content=ft.Column(
                    controls=[
                        detail_header,
                        detail_duplicate,
                        detail_menu,
                        ft.Container(
                            expand=True,
                            content=detail_body,
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

    batch_filter_search_field = text_input("Buscar grupo", width=260)
    batch_filter_status_field = text_input("Estado", width=150)
    batch_filter_client_id_field = text_input("Cliente ID", width=120)
    batch_filter_expedient_id_field = text_input("Expediente ID", width=140)

    def _batch_filter_kwargs():
        raw_status = str(batch_filter_status_field.value or "").strip()
        raw_client_id = str(batch_filter_client_id_field.value or "").strip()
        raw_expedient_id = str(batch_filter_expedient_id_field.value or "").strip()
        raw_search = str(batch_filter_search_field.value or "").strip()

        kwargs = {"limit": 50}

        if raw_status:
            kwargs["status"] = raw_status

        if raw_client_id:
            kwargs["client_id"] = int(raw_client_id)

        if raw_expedient_id:
            kwargs["expedient_id"] = int(raw_expedient_id)

        if raw_search:
            kwargs["search"] = raw_search

        return kwargs

    def clear_batch_filters(e=None):
        batch_filter_search_field.value = ""
        batch_filter_status_field.value = ""
        batch_filter_client_id_field.value = ""
        batch_filter_expedient_id_field.value = ""
        refresh_batches_panel()

    def apply_batch_filters(e=None):
        refresh_batches_panel()

    def quick_copy_batch_from_list(batch_id):
        try:
            batch = document_inbox_service.get_document_inbox_batch(int(batch_id))
            expedient_id = batch.get("expedient_id")
            subfolder = str(batch.get("target_box_folder") or "").strip()

            if not expedient_id:
                raise ValueError("El grupo no tiene expediente destino. Abre el grupo y asígnalo antes de copiar.")

            result = document_inbox_service.copy_document_inbox_batch_to_expedient_box(
                int(batch_id),
                expedient_id=int(expedient_id),
                subfolder=subfolder,
            )

            copy_result = result.get("copy_result") or {}
            batches_panel_message.content = success_alert(
                f"Grupo #{batch_id} copiado a Box. "
                f"Copiados: {copy_result.get('copied_count', 0)} · "
                f"Omitidos: {copy_result.get('skipped_count', 0)} · "
                f"Errores: {copy_result.get('error_count', 0)}"
            )
            refresh_batches_panel()
        except Exception as exc:
            batches_panel_message.content = error_alert(f"No se pudo copiar el grupo #{batch_id} a Box: {exc}")
            try:
                batches_panel_message.update()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass

    def build_batches_panel_content():
        rows = []

        try:
            batches = document_inbox_service.list_document_inbox_batches(**_batch_filter_kwargs())
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
                client_id = batch.get("client_id") or "-"
                expedient_id = batch.get("expedient_id") or "-"
                target_folder = batch.get("target_box_folder") or "-"

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
                                        ft.Text(
                                            f"Cliente: {client_id} · Expediente: {expedient_id} · Carpeta: {target_folder}",
                                            size=10,
                                            color=Q_MUTED,
                                            selectable=True,
                                        ),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                secondary_button("Ver grupo", lambda e, batch_id=batch_id: open_batch_detail_dialog(batch_id)),
                                secondary_button("Copiar a Box", lambda e, batch_id=batch_id: quick_copy_batch_from_list(batch_id)),
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
                    ft.Row(
                        controls=[
                            batch_filter_search_field,
                            batch_filter_status_field,
                            batch_filter_client_id_field,
                            batch_filter_expedient_id_field,
                            primary_button("Aplicar filtros", apply_batch_filters),
                            secondary_button("Limpiar", clear_batch_filters),
                        ],
                        spacing=8,
                        wrap=True,
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
    batch_target_expedient_id_field = text_input("Expediente ID destino", width=220)
    batch_target_subfolder_field = text_input("Subcarpeta Box destino", width=360)

    batch_edit_name_field = text_input("Nombre del grupo", width=680)
    batch_edit_notes_field = multiline_input("Notas del grupo", width=680)
    batch_edit_subfolder_field = text_input("Subcarpeta Box destino", width=360)
    batch_edit_status_field = text_input("Estado del grupo", width=220)
    batch_edit_client_label_to_id = {}
    batch_edit_expedient_label_to_id = {}

    def _batch_metadata_dict(raw):
        try:
            if isinstance(raw, dict):
                return raw
            if not raw:
                return {}
            parsed = json.loads(str(raw))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


    def _batch_edit_client_labels():
        batch_edit_client_label_to_id.clear()
        options = document_inbox_service.client_autocomplete_options()
        for item in options:
            label = item.get("label")
            if label:
                batch_edit_client_label_to_id[label] = int(item.get("id"))
        return list(batch_edit_client_label_to_id.keys())

    def _batch_edit_expedient_labels_for_client(client_id):
        batch_edit_expedient_label_to_id.clear()
        if not client_id:
            return []

        options = document_inbox_service.expedient_autocomplete_options_for_client(int(client_id))
        for item in options:
            label = item.get("label")
            if label:
                batch_edit_expedient_label_to_id[label] = int(item.get("id"))
        return list(batch_edit_expedient_label_to_id.keys())

    def _batch_edit_find_client_label(client_id):
        if not client_id:
            return ""

        target = int(client_id)
        for label, value in batch_edit_client_label_to_id.items():
            if int(value) == target:
                return label

        _batch_edit_client_labels()
        for label, value in batch_edit_client_label_to_id.items():
            if int(value) == target:
                return label

        return ""

    def _batch_edit_find_expedient_label(expedient_id):
        if not expedient_id:
            return ""

        target = int(expedient_id)
        for label, value in batch_edit_expedient_label_to_id.items():
            if int(value) == target:
                return label

        return ""

    def on_batch_edit_client_selected(value):
        client_id = batch_edit_client_label_to_id.get(value)
        state["batch_edit_client_id"] = int(client_id) if client_id else None
        state["batch_edit_expedient_id"] = None

        expedient_labels = _batch_edit_expedient_labels_for_client(state.get("batch_edit_client_id"))
        batch_edit_expedient_autocomplete.set_options(expedient_labels, clear_value=True)
        batch_edit_expedient_autocomplete.input.label = (
            f"Expediente destino ({len(expedient_labels)})"
            if expedient_labels
            else "Expediente destino (sin expedientes)"
        )
        page.update()

    def on_batch_edit_expedient_selected(value):
        expedient_id = batch_edit_expedient_label_to_id.get(value)
        state["batch_edit_expedient_id"] = int(expedient_id) if expedient_id else None
        page.update()

    batch_edit_client_autocomplete = AppAutocomplete(
        page=page,
        label="Cliente destino",
        options=_batch_edit_client_labels(),
        width=520,
        max_results=12,
        on_select=on_batch_edit_client_selected,
        allow_free_text=False,
    )

    batch_edit_expedient_autocomplete = AppAutocomplete(
        page=page,
        label="Expediente destino",
        options=[],
        width=520,
        max_results=12,
        on_select=on_batch_edit_expedient_selected,
        allow_free_text=False,
    )


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

    def save_open_batch_changes(e=None):
        try:
            batch_id = int(state.get("open_batch_id") or 0)
            if not batch_id:
                raise ValueError("No hay grupo documental abierto.")

            name = str(batch_edit_name_field.value or "").strip()
            if not name:
                raise ValueError("El nombre del grupo es obligatorio.")

            client_id = state.get("batch_edit_client_id")
            expedient_id = state.get("batch_edit_expedient_id")

            updated = document_inbox_service.update_document_inbox_batch(
                batch_id,
                name=name,
                notes=batch_edit_notes_field.value or "",
                client_id=int(client_id) if client_id else None,
                expedient_id=int(expedient_id) if expedient_id else None,
                target_box_folder=batch_edit_subfolder_field.value or "",
                status=batch_edit_status_field.value or "draft",
            )

            batch_detail_message.content = success_alert(
                f"Grupo actualizado: #{updated.get('id')} · {updated.get('name')}"
            )

            open_batch_detail_dialog(batch_id)
            refresh_batches_panel()
        except Exception as exc:
            batch_detail_message.content = error_alert(f"No se pudieron guardar los cambios del grupo: {exc}")
            try:
                batch_detail_message.update()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass


    def copy_open_batch_to_box(e=None):
        try:
            batch_id = int(state.get("open_batch_id") or 0)
            if not batch_id:
                raise ValueError("No hay grupo documental abierto.")

            raw_expedient_id = str(batch_target_expedient_id_field.value or "").strip()
            expedient_id = int(raw_expedient_id) if raw_expedient_id else None
            subfolder = str(batch_target_subfolder_field.value or "").strip()

            result = document_inbox_service.copy_document_inbox_batch_to_expedient_box(
                batch_id,
                expedient_id=expedient_id,
                subfolder=subfolder,
            )

            copy_result = result.get("copy_result") or {}
            batch_detail_message.content = success_alert(
                f"Grupo copiado a Box. Copiados: {copy_result.get('copied_count', 0)} · "
                f"Omitidos: {copy_result.get('skipped_count', 0)} · "
                f"Errores: {copy_result.get('error_count', 0)} · "
                f"Estado: {copy_result.get('status') or '-'}"
            )

            open_batch_detail_dialog(batch_id)
            refresh_batches_panel()
        except Exception as exc:
            batch_detail_message.content = error_alert(f"No se pudo copiar el grupo a Box: {exc}")
            try:
                batch_detail_message.update()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass

    def add_selected_items_to_open_batch(e=None):
        try:
            batch_id = int(state.get("open_batch_id") or 0)
            if not batch_id:
                raise ValueError("No hay grupo documental abierto.")

            selected_ids = list(state.get("selected_item_ids") or [])
            if not selected_ids:
                raise ValueError("Selecciona documentos en la bandeja antes de añadirlos al grupo.")

            result = document_inbox_service.add_items_to_document_inbox_batch(batch_id, selected_ids)
            add_result = result.get("add_result") or {}

            batch_detail_message.content = success_alert(
                f"Añadidos: {add_result.get('added_count', 0)} · "
                f"Omitidos: {add_result.get('skipped_count', 0)}"
            )

            state["selected_item_ids"] = set()
            selected_label.value = "Ningún documento seleccionado."

            open_batch_detail_dialog(batch_id)
            refresh_items()
            refresh_batches_panel()
        except Exception as exc:
            batch_detail_message.content = error_alert(f"No se pudieron añadir documentos al grupo: {exc}")
            try:
                batch_detail_message.update()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass

    def remove_item_from_open_batch(item_id):
        try:
            batch_id = int(state.get("open_batch_id") or 0)
            if not batch_id:
                raise ValueError("No hay grupo documental abierto.")

            document_inbox_service.remove_item_from_document_inbox_batch(batch_id, int(item_id))

            batch_detail_message.content = success_alert(f"Documento #{item_id} quitado del grupo.")
            open_batch_detail_dialog(batch_id)
            refresh_batches_panel()
        except Exception as exc:
            batch_detail_message.content = error_alert(f"No se pudo quitar el documento del grupo: {exc}")
            try:
                batch_detail_message.update()
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass

    def set_open_batch_status(new_status):
        try:
            batch_id = int(state.get("open_batch_id") or 0)
            if not batch_id:
                raise ValueError("No hay grupo documental abierto.")

            document_inbox_service.update_document_inbox_batch_status(batch_id, new_status)
            batch_detail_message.content = success_alert(f"Estado del grupo actualizado a {new_status}.")
            open_batch_detail_dialog(batch_id)
            refresh_batches_panel()
        except Exception as exc:
            batch_detail_message.content = error_alert(f"No se pudo cambiar el estado del grupo: {exc}")
            try:
                batch_detail_message.update()
            except Exception:
                pass
            try:
                page.update()
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
        state["open_batch_id"] = int(batch_id)

        try:
            batch = document_inbox_service.get_document_inbox_batch(int(batch_id))

            batch_target_expedient_id_field.value = str(batch.get("expedient_id") or "")
            batch_target_subfolder_field.value = str(batch.get("target_box_folder") or "")

            batch_edit_name_field.value = str(batch.get("name") or "")
            batch_edit_notes_field.value = str(batch.get("notes") or "")
            batch_edit_subfolder_field.value = str(batch.get("target_box_folder") or "")
            batch_edit_status_field.value = str(batch.get("status") or "draft")

            state["batch_edit_client_id"] = int(batch.get("client_id")) if batch.get("client_id") else None
            state["batch_edit_expedient_id"] = int(batch.get("expedient_id")) if batch.get("expedient_id") else None

            batch_edit_client_autocomplete.set_options(_batch_edit_client_labels(), clear_value=True)
            client_label = _batch_edit_find_client_label(state.get("batch_edit_client_id"))
            batch_edit_client_autocomplete.input.value = client_label or ""

            expedient_labels = _batch_edit_expedient_labels_for_client(state.get("batch_edit_client_id"))
            batch_edit_expedient_autocomplete.set_options(expedient_labels, clear_value=True)
            expedient_label = _batch_edit_find_expedient_label(state.get("batch_edit_expedient_id"))
            batch_edit_expedient_autocomplete.input.value = expedient_label or ""

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

            metadata = _batch_metadata_dict(batch.get("metadata_json"))
            last_copy = metadata.get("last_copy_to_box") if isinstance(metadata, dict) else None
            if isinstance(last_copy, dict):
                rows.append(
                    ft.Container(
                        bgcolor="#ECFDF3" if int(last_copy.get("error_count") or 0) == 0 else "#FFF7E6",
                        border=ft.border.all(
                            1,
                            "#ABEFC6" if int(last_copy.get("error_count") or 0) == 0 else "#F79009",
                        ),
                        border_radius=12,
                        padding=10,
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    "Último traslado a Box",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color="#027A48" if int(last_copy.get("error_count") or 0) == 0 else "#B54708",
                                ),
                                ft.Text(
                                    f"Fecha: {last_copy.get('at') or '-'} · "
                                    f"Expediente: {last_copy.get('expedient_id') or '-'} · "
                                    f"Subcarpeta: {last_copy.get('subfolder') or '-'}",
                                    size=11,
                                    color=Q_MUTED,
                                    selectable=True,
                                ),
                                ft.Text(
                                    f"Copiados: {last_copy.get('copied_count', 0)} · "
                                    f"Omitidos: {last_copy.get('skipped_count', 0)} · "
                                    f"Errores: {last_copy.get('error_count', 0)}",
                                    size=12,
                                    color=Q_PRIMARY_DARK,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=6,
                        ),
                    )
                )

            rows.append(
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=10,
                    content=ft.Column(
                        controls=[
                            ft.Text("Editar grupo", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(
                                "Actualiza la cabecera del grupo documental. No mueve ni borra documentos.",
                                size=11,
                                color=Q_MUTED,
                            ),
                            batch_edit_name_field,
                            batch_edit_notes_field,
                            ft.Row(
                                controls=[
                                    batch_edit_client_autocomplete.control,
                                    batch_edit_expedient_autocomplete.control,
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                            ft.Row(
                                controls=[
                                    batch_edit_subfolder_field,
                                    batch_edit_status_field,
                                    primary_button("Guardar cambios", save_open_batch_changes),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                        ],
                        spacing=8,
                    ),
                )
            )

            rows.append(
                ft.Container(
                    bgcolor="#FFFFFF",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=10,
                    content=ft.Column(
                        controls=[
                            ft.Text("Gestionar grupo", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(
                                "Añade documentos seleccionados en la bandeja, cambia el estado del grupo o revisa el lote.",
                                size=11,
                                color=Q_MUTED,
                            ),
                            ft.Row(
                                controls=[
                                    secondary_button("Añadir seleccionados al grupo", add_selected_items_to_open_batch),
                                    secondary_button("Estado: draft", lambda e: set_open_batch_status("draft")),
                                    secondary_button("Estado: reviewed", lambda e: set_open_batch_status("reviewed")),
                                    secondary_button("Estado: copied_to_box", lambda e: set_open_batch_status("copied_to_box")),
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                        ],
                        spacing=8,
                    ),
                )
            )

            rows.append(
                ft.Container(
                    bgcolor="#F8FAFC",
                    border=ft.border.all(1, Q_BORDER),
                    border_radius=12,
                    padding=10,
                    content=ft.Column(
                        controls=[
                            ft.Text("Trasladar grupo a expediente / Box", size=14, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text(
                                "Copia documentos válidos del grupo a la carpeta Box del expediente. "
                                "No borra ni mueve los originales. Se omiten duplicados y descartados.",
                                size=11,
                                color=Q_MUTED,
                            ),
                            ft.Row(
                                controls=[
                                    batch_target_expedient_id_field,
                                    batch_target_subfolder_field,
                                    primary_button("Copiar grupo a Box expediente", copy_open_batch_to_box),
                                ],
                                spacing=10,
                                wrap=True,
                            ),
                        ],
                        spacing=8,
                    ),
                )
            )

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
                                danger_button("Quitar", lambda e, item=item: remove_item_from_open_batch(item.get("id"))),
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
    batch_target_folder_create_field = text_input("Subcarpeta destino sugerida", width=360)
    batch_notes_field = multiline_input("Notas del grupo", width=680)
    batch_dialog_message = ft.Container()
    batch_selected_docs_box = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
    batch_create_client_label_to_id = {}
    batch_create_expedient_label_to_id = {}

    def close_create_batch_dialog(e=None):
        create_batch_dialog.open = False
        try:
            page.update()
        except Exception:
            pass

    def _batch_create_client_labels():
        batch_create_client_label_to_id.clear()
        options = document_inbox_service.client_autocomplete_options()
        for item in options:
            label = item.get("label")
            if label:
                batch_create_client_label_to_id[label] = int(item.get("id"))
        return list(batch_create_client_label_to_id.keys())

    def _batch_create_expedient_labels_for_client(client_id):
        batch_create_expedient_label_to_id.clear()
        if not client_id:
            return []

        options = document_inbox_service.expedient_autocomplete_options_for_client(int(client_id))
        for item in options:
            label = item.get("label")
            if label:
                batch_create_expedient_label_to_id[label] = int(item.get("id"))
        return list(batch_create_expedient_label_to_id.keys())

    def _batch_find_client_label(client_id):
        if not client_id:
            return ""
        target = int(client_id)
        for label, value in batch_create_client_label_to_id.items():
            if int(value) == target:
                return label
        _batch_create_client_labels()
        for label, value in batch_create_client_label_to_id.items():
            if int(value) == target:
                return label
        return ""

    def _batch_find_expedient_label(expedient_id):
        if not expedient_id:
            return ""
        target = int(expedient_id)
        for label, value in batch_create_expedient_label_to_id.items():
            if int(value) == target:
                return label
        return ""

    def on_batch_create_client_selected(value):
        client_id = batch_create_client_label_to_id.get(value)
        state["batch_create_client_id"] = int(client_id) if client_id else None
        state["batch_create_expedient_id"] = None

        expedient_labels = _batch_create_expedient_labels_for_client(state.get("batch_create_client_id"))
        batch_create_expedient_autocomplete.set_options(expedient_labels, clear_value=True)
        batch_create_expedient_autocomplete.input.label = (
            f"Expediente destino ({len(expedient_labels)})"
            if expedient_labels
            else "Expediente destino (sin expedientes)"
        )
        page.update()

    def on_batch_create_expedient_selected(value):
        expedient_id = batch_create_expedient_label_to_id.get(value)
        state["batch_create_expedient_id"] = int(expedient_id) if expedient_id else None
        page.update()

    batch_create_client_autocomplete = AppAutocomplete(
        page=page,
        label="Cliente destino",
        options=_batch_create_client_labels(),
        width=520,
        max_results=12,
        on_select=on_batch_create_client_selected,
        allow_free_text=False,
    )

    batch_create_expedient_autocomplete = AppAutocomplete(
        page=page,
        label="Expediente destino",
        options=[],
        width=520,
        max_results=12,
        on_select=on_batch_create_expedient_selected,
        allow_free_text=False,
    )

    def analyze_batch_selection(selected_ids):
        valid_items = []
        skipped_items = []
        expedient_ids = set()
        client_ids = set()

        for item_id in selected_ids:
            try:
                item = document_inbox_service.get_inbox_item(int(item_id))
            except Exception as exc:
                skipped_items.append({
                    "id": item_id,
                    "reason": f"error: {exc}",
                    "filename": "-",
                })
                continue

            status_value = str(item.get("status") or "").strip().lower()
            if status_value in {"duplicate", "discarded"}:
                skipped_items.append({
                    "id": item.get("id"),
                    "reason": f"status_{status_value}",
                    "filename": item.get("original_filename") or "-",
                })
                continue

            valid_items.append(item)

            if item.get("expedient_id"):
                expedient_ids.add(int(item.get("expedient_id")))

            if item.get("client_id"):
                client_ids.add(int(item.get("client_id")))

        return {
            "valid_items": valid_items,
            "skipped_items": skipped_items,
            "expedient_ids": expedient_ids,
            "client_ids": client_ids,
        }

    def render_batch_selected_docs():
        selected_ids = list(state.get("selected_item_ids") or [])
        analysis = analyze_batch_selection(selected_ids)
        valid_items = analysis.get("valid_items") or []
        skipped_items = analysis.get("skipped_items") or []

        rows = []

        if not selected_ids:
            rows.append(empty_state("No hay documentos seleccionados."))
        else:
            rows.append(
                ft.Text(
                    f"Selección: {len(selected_ids)} · Válidos: {len(valid_items)} · Omitidos: {len(skipped_items)}",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=Q_PRIMARY_DARK,
                )
            )

        if skipped_items:
            rows.append(
                ft.Container(
                    bgcolor="#FFF7E6",
                    border=ft.border.all(1, "#F79009"),
                    border_radius=10,
                    padding=8,
                    content=ft.Column(
                        controls=[
                            ft.Text("Documentos que no entrarán en el grupo", size=12, weight=ft.FontWeight.BOLD, color="#B54708"),
                            *[
                                ft.Text(
                                    f"#{item.get('id')} · {item.get('filename')} · {item.get('reason')}",
                                    size=11,
                                    color="#B54708",
                                )
                                for item in skipped_items[:8]
                            ],
                        ],
                        spacing=4,
                    ),
                )
            )

        if valid_items:
            rows.append(ft.Text("Documentos válidos", size=12, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK))

        for item in valid_items:
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
                                f"Estado: {item.get('status') or '-'} · Cliente: {item.get('client_id') or '-'} · Expediente: {item.get('expedient_id') or '-'}",
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
        batch_target_folder_create_field.value = "PARA PRESENTAR"
        batch_notes_field.value = ""
        state["batch_create_client_id"] = None
        state["batch_create_expedient_id"] = None
        batch_create_client_autocomplete.set_options(_batch_create_client_labels(), clear_value=True)
        batch_create_expedient_autocomplete.set_options([], clear_value=True)

        analysis = analyze_batch_selection(selected_ids)
        valid_items = analysis.get("valid_items") or []
        skipped_items = analysis.get("skipped_items") or []
        expedient_ids = analysis.get("expedient_ids") or set()
        client_ids = analysis.get("client_ids") or set()

        if len(expedient_ids) == 1:
            expedient_id = next(iter(expedient_ids))
            state["batch_create_expedient_id"] = int(expedient_id)

            if len(client_ids) == 1:
                client_id = next(iter(client_ids))
                state["batch_create_client_id"] = int(client_id)
                client_label = _batch_find_client_label(client_id)
                if client_label:
                    batch_create_client_autocomplete.input.value = client_label

                expedient_labels = _batch_create_expedient_labels_for_client(client_id)
                batch_create_expedient_autocomplete.set_options(expedient_labels, clear_value=True)
                expedient_label = _batch_find_expedient_label(expedient_id)
                if expedient_label:
                    batch_create_expedient_autocomplete.input.value = expedient_label

            batch_name_field.value = f"EXPEDIENTE #{expedient_id} - PARA PRESENTAR ({len(valid_items)} documentos)"
        elif valid_items:
            batch_name_field.value = f"Grupo documental ({len(valid_items)} documentos válidos)"
        elif selected_ids:
            batch_name_field.value = f"Grupo documental ({len(selected_ids)} seleccionados)"
        else:
            batch_name_field.value = "Grupo documental"

        messages = []
        if skipped_items:
            messages.append(f"Se omitirán {len(skipped_items)} documento(s) duplicate/discarded/no válidos.")
        if len(expedient_ids) > 1:
            messages.append("Aviso: los documentos válidos pertenecen a expedientes distintos.")
        if len(client_ids) > 1:
            messages.append("Aviso: los documentos válidos pertenecen a clientes distintos.")

        if messages:
            batch_dialog_message.content = error_alert(" ".join(messages))

        render_batch_selected_docs()

        if create_batch_dialog not in page.overlay:
            page.overlay.append(create_batch_dialog)

        create_batch_dialog.open = True
        page.update()

    def create_batch_from_selection(e=None):
        selected_ids = list(state.get("selected_item_ids") or [])
        analysis = analyze_batch_selection(selected_ids)
        valid_items = analysis.get("valid_items") or []
        skipped_items = analysis.get("skipped_items") or []
        valid_ids = [int(item.get("id")) for item in valid_items if item.get("id")]

        if not valid_ids:
            batch_dialog_message.content = error_alert(
                "No hay documentos válidos para crear el grupo. Se omiten duplicados y descartados."
            )
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
            client_id = state.get("batch_create_client_id")
            expedient_id = state.get("batch_create_expedient_id")
            target_folder = str(batch_target_folder_create_field.value or "").strip()

            batch = document_inbox_service.create_document_inbox_batch(
                name=name,
                inbox_item_ids=valid_ids,
                client_id=int(client_id) if client_id else None,
                expedient_id=int(expedient_id) if expedient_id else None,
                target_box_folder=target_folder,
                notes=batch_notes_field.value or "",
            )

            state["selected_item_ids"] = set()
            selected_label.value = "Ningún documento seleccionado."

            msg = f"Grupo #{batch.get('id')} creado con {batch.get('item_count')} documento(s)."
            if skipped_items:
                msg += f" Omitidos: {len(skipped_items)}."

            batch_dialog_message.content = success_alert(msg)

            refresh_items()
            refresh_batches_panel()
            render_batch_selected_docs()

            try:
                selected_label.update()
            except Exception:
                pass
            try:
                batch_dialog_message.update()
            except Exception:
                pass
            try:
                batch_selected_docs_box.update()
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
                    ft.Row(
                        controls=[
                            batch_create_client_autocomplete.control,
                            batch_create_expedient_autocomplete.control,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Row(
                        controls=[
                            batch_target_folder_create_field,
                        ],
                        spacing=10,
                        wrap=True,
                    ),
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
                        secondary_button("Actualizar", lambda e: refresh_items(e, scan_watch=True)),
                        secondary_button("Anterior", previous_document_page),
                        secondary_button("Siguiente", next_document_page),
                        pagination_label,
                        watch_scan_notice,
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

