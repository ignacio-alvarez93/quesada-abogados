import flet as ft

from backend.services import presentation_queue_service as queue_service
from frontend.components.app_button import primary_button, secondary_button, danger_button
from frontend.components.app_alert import error_alert, success_alert
from frontend.components.app_card import metric_card
from frontend.components.app_empty_state import empty_state
from frontend.components.document_file_card import document_file_card
from frontend.components.listing import compact_pagination_bar, counter_chips

Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"

QUEUE_STATUS_MAP = {
    "pendiente": ("Pendiente", "#FFF7E6", "#B54708"),
    "en_proceso": ("En proceso", "#EAF3FF", "#0057B8"),
    "lanzado": ("Lanzado", "#EEF4FF", "#3538CD"),
    "completado": ("Presentado", "#ECFDF3", "#027A48"),
    "error": ("Error", "#FEF3F2", "#B42318"),
    "cancelado": ("Cancelado", "#F2F4F7", "#475467"),
    "todos": ("Todos", "#F8FAFC", "#64748B"),
}


def _estado_badge(estado):
    colors = {
        "pendiente": ("#FFF7E6", "#B54708"),
        "en_proceso": ("#EAF3FF", "#0057B8"),
        "lanzado": ("#EEF4FF", "#3538CD"),
        "completado": ("#ECFDF3", "#027A48"),
        "error": ("#FEF3F2", "#B42318"),
        "cancelado": ("#F2F4F7", "#475467"),
    }
    bg, fg = colors.get(estado or "", ("#F2F4F7", "#475467"))
    return ft.Container(
        bgcolor=bg,
        border_radius=999,
        padding=ft.padding.symmetric(horizontal=10, vertical=4),
        content=ft.Text(
            (estado or "-").replace("_", " ").upper(),
            size=11,
            weight=ft.FontWeight.BOLD,
            color=fg,
        ),
    )


def presentation_queue_view(page: ft.Page, on_open_expediente=None):
    state = {
        "items": [],
        "counts": {},
        "message": None,
        "filter": "todos",
        "selected_ids": set(),
        "page": 1,
        "page_size": 10,
        "total_all_items": 0,
    }

    content_area = ft.Container(expand=True)

    def set_message(control):
        state["message"] = control

    def load():
        backend_counts = queue_service.counts_by_estado() or {}
        all_items = queue_service.list_queue(estado="todos", limit=200) or []

        visual_counts = dict(backend_counts)
        derived_counts = {}

        for queue_item in all_items:
            estado = queue_item.get("estado") or ""
            if estado:
                derived_counts[estado] = derived_counts.get(estado, 0) + 1

        visual_counts.update(derived_counts)

        state["counts"] = visual_counts
        state["total_all_items"] = len(all_items)

        if state["filter"] == "todos":
            state["items"] = all_items
        else:
            state["items"] = queue_service.list_queue(estado=state["filter"], limit=200)

    def refresh(e=None):
        load()
        content_area.content = build_content()
        page.update()

    def set_filter(value):
        state["filter"] = value
        state["page"] = 1
        state["selected_ids"] = set()
        refresh()

    def execute_item(queue_id):
        try:
            result = queue_service.execute_queue_item(queue_id)
            set_message(success_alert(f"Presentación lanzada correctamente. PID: {result.get('pid') or '-'}"))
        except Exception as exc:
            set_message(error_alert(str(exc)))
        refresh()

    def cancel_item(queue_id):
        try:
            queue_service.mark_cancelled(queue_id)
            set_message(success_alert("Elemento cancelado"))
        except Exception as exc:
            set_message(error_alert(str(exc)))
        refresh()

    def retry_item(queue_id):
        try:
            queue_service.reset_to_pending(queue_id)
            set_message(success_alert("Elemento devuelto a pendiente"))
        except Exception as exc:
            set_message(error_alert(str(exc)))
        refresh()

    def open_expediente(expediente_id):
        if on_open_expediente:
            on_open_expediente(expediente_id)
        else:
            set_message(error_alert("No hay navegación configurada para abrir expedientes"))
            refresh()

    def set_page(page_number):
        state["page"] = max(1, int(page_number or 1))
        content_area.content = build_content()
        page.update()

    def toggle_queue_selection(queue_id, event=None):
        selected_ids = set(state.get("selected_ids") or set())
        if queue_id in selected_ids:
            selected_ids.remove(queue_id)
        else:
            selected_ids.add(queue_id)
        state["selected_ids"] = selected_ids
        content_area.content = build_content()
        page.update()

    def clear_queue_selection(e=None):
        state["selected_ids"] = set()
        content_area.content = build_content()
        page.update()

    def filter_button(label, value):
        if state["filter"] == value:
            return primary_button(label, lambda e, v=value: set_filter(v))
        return secondary_button(label, lambda e, v=value: set_filter(v))

    def queue_card(item):
        estado = item.get("estado")

        can_execute = estado in ("pendiente", "error")
        can_cancel = estado in ("pendiente", "error", "en_proceso", "lanzado")
        can_retry = estado in ("error", "cancelado")

        menu_items = []

        menu_items.append(
            {
                "label": "Abrir expediente",
                "on_click": lambda e, eid=item["expediente_id"]: open_expediente(eid),
            }
        )

        if can_execute:
            menu_items.append(
                {
                    "label": "Ejecutar",
                    "on_click": lambda e, qid=item["id"]: execute_item(qid),
                }
            )

        if can_retry:
            menu_items.append(
                {
                    "label": "Reintentar",
                    "on_click": lambda e, qid=item["id"]: retry_item(qid),
                }
            )

        if can_cancel:
            menu_items.append(
                {
                    "label": "Cancelar",
                    "on_click": lambda e, qid=item["id"]: cancel_item(qid),
                    "danger": True,
                }
            )

        extra_lines = [
            ft.Row(
                controls=[
                    ft.Text(item.get("cliente_nombre") or "Cliente no indicado", size=12, color=Q_MUTED),
                    _estado_badge(estado),
                ],
                spacing=8,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            item.get("tipo_expediente") or "Tipo no indicado",
            f"Expediente ID: {item.get('expediente_id')} · Cola ID: {item.get('id')} · Intentos: {item.get('intentos') or 0}",
            f"Creado: {item.get('created_at') or '-'} · Lanzado: {item.get('started_at') or '-'} · PID: {item.get('pid') or '-'}",
        ]

        if estado == "lanzado":
            extra_lines.append(
                ft.Text(
                    "Pendiente de justificante de presentación",
                    size=12,
                    color="#3538CD",
                    weight=ft.FontWeight.BOLD,
                )
            )

        if item.get("last_error"):
            extra_lines.append(
                ft.Text(
                    item.get("last_error") or "",
                    size=12,
                    color="#B42318",
                    selectable=True,
                )
            )

        queue_id = item.get("id")
        selected = queue_id in (state.get("selected_ids") or set())

        card_title = item.get("numero_expediente") or f"Expediente #{item.get('expediente_id')}"
        client_title = item.get("cliente_nombre") or "Cliente no indicado"

        return document_file_card(
            name=f"{card_title} · {client_title}",
            file_type="queue",
            selected=selected,
            selectable=True,
            checkbox_value=selected,
            on_select=lambda e, qid=queue_id: toggle_queue_selection(qid, e),
            extra_lines=extra_lines,
            action_groups=[
                {
                    "items": menu_items,
                }
            ],
            compact=False,
        )

    def build_content():
        counts = state["counts"] or {}
        items = state["items"] or []

        controls = [
            ft.Row(
                controls=[
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text("Colas de presentación", size=28, weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                            ft.Text("Centro de control de presentaciones asistidas Mercurio", size=14, color=Q_MUTED),
                        ],
                    ),
                    secondary_button("Actualizar", refresh),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Row(
                controls=[
                    metric_card("Pendientes", counts.get("pendiente", 0)),
                    metric_card("En proceso", counts.get("en_proceso", 0)),
                    metric_card("Lanzados", counts.get("lanzado", 0)),
                    metric_card("Presentados", counts.get("completado", 0)),
                    metric_card("Errores", counts.get("error", 0)),
                ],
                spacing=12,
                wrap=True,
            ),
            counter_chips(
                options=[
                    ("pendiente", "Pendientes"),
                    ("en_proceso", "En proceso"),
                    ("lanzado", "Lanzados"),
                    ("error", "Errores"),
                    ("completado", "Presentados"),
                    ("cancelado", "Cancelados"),
                ],
                counts={**counts, "todos": state.get("total_all_items", len(items))},
                active_value=state["filter"],
                on_select=set_filter,
                include_all=True,
                all_label="Todos",
                all_value="todos",
                status_map=QUEUE_STATUS_MAP,
                bordered_status=True,
            ),
        ]

        if state["message"]:
            controls.append(state["message"])

        total_items = len(items)
        page_size = int(state.get("page_size") or 20)
        current_page = max(1, int(state.get("page") or 1))
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        current_page = min(current_page, total_pages)
        state["page"] = current_page

        start = (current_page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]

        selected_count = len(state.get("selected_ids") or set())
        if selected_count:
            controls.append(
                ft.Row(
                    controls=[
                        ft.Text(
                            f"Seleccionados: {selected_count}",
                            size=12,
                            color=Q_PRIMARY_DARK,
                            weight=ft.FontWeight.BOLD,
                        ),
                        secondary_button("Limpiar selección", clear_queue_selection),
                    ],
                    spacing=8,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )

        if total_items:
            controls.append(
                compact_pagination_bar(
                    page=current_page,
                    page_size=page_size,
                    total_items=total_items,
                    on_page_change=set_page,
                    label_prefix="Cola",
                )
            )

        if not items:
            controls.append(empty_state("No hay expedientes en esta cola"))
        else:
            controls.extend(queue_card(item) for item in page_items)

        return ft.Column(
            controls=controls,
            spacing=18,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

    load()
    content_area.content = build_content()
    return content_area
