import flet as ft

from backend.services import presentation_queue_service as queue_service
from frontend.components.app_button import primary_button, secondary_button, danger_button
from frontend.components.app_alert import error_alert, success_alert
from frontend.components.app_card import metric_card
from frontend.components.app_empty_state import empty_state

Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#E4E7EC"


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
    }

    content_area = ft.Container(expand=True)

    def set_message(control):
        state["message"] = control

    def load():
        state["counts"] = queue_service.counts_by_estado()
        state["items"] = queue_service.list_queue(estado=state["filter"], limit=200)

    def refresh(e=None):
        load()
        content_area.content = build_content()
        page.update()

    def set_filter(value):
        state["filter"] = value
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

    def filter_button(label, value):
        if state["filter"] == value:
            return primary_button(label, lambda e, v=value: set_filter(v))
        return secondary_button(label, lambda e, v=value: set_filter(v))

    def queue_card(item):
        estado = item.get("estado")

        can_execute = estado in ("pendiente", "error")
        can_cancel = estado in ("pendiente", "error", "en_proceso", "lanzado")
        can_retry = estado in ("error", "cancelado")

        actions = []

        actions.append(secondary_button("Abrir expediente", lambda e, eid=item["expediente_id"]: open_expediente(eid)))

        if can_execute:
            actions.append(primary_button("Ejecutar", lambda e, qid=item["id"]: execute_item(qid)))

        if can_retry:
            actions.append(secondary_button("Reintentar", lambda e, qid=item["id"]: retry_item(qid)))

        if can_cancel:
            actions.append(danger_button("Cancelar", lambda e, qid=item["id"]: cancel_item(qid)))

        return ft.Container(
            bgcolor="#FFFFFF",
            border=ft.border.all(1, Q_BORDER),
            border_radius=14,
            padding=14,
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        item.get("numero_expediente") or f"Expediente #{item.get('expediente_id')}",
                                        size=15,
                                        weight=ft.FontWeight.BOLD,
                                        color=Q_PRIMARY_DARK,
                                    ),
                                    ft.Text(item.get("cliente_nombre") or "Cliente no indicado", size=12, color=Q_MUTED),
                                    ft.Text(item.get("tipo_expediente") or "Tipo no indicado", size=12, color=Q_MUTED),
                                ],
                            ),
                            _estado_badge(estado),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text(f"Expediente ID: {item.get('expediente_id')}", size=11, color=Q_MUTED),
                            ft.Text(f"Cola ID: {item.get('id')}", size=11, color=Q_MUTED),
                            ft.Text(f"Intentos: {item.get('intentos') or 0}", size=11, color=Q_MUTED),
                            ft.Text(f"Creado: {item.get('created_at') or '-'}", size=11, color=Q_MUTED),
                            ft.Text(f"Lanzado: {item.get('started_at') or '-'}", size=11, color=Q_MUTED),
                            ft.Text(f"PID: {item.get('pid') or '-'}", size=11, color=Q_MUTED),
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                    ft.Text(
                        "Pendiente de justificante de presentación",
                        size=12,
                        color="#3538CD",
                        weight=ft.FontWeight.BOLD,
                        visible=estado == "lanzado",
                    ),
                    ft.Text(
                        item.get("last_error") or "",
                        size=12,
                        color="#B42318",
                        visible=bool(item.get("last_error")),
                        selectable=True,
                    ),
                    ft.Row(controls=actions, spacing=8, wrap=True),
                ],
            ),
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
            ft.Row(
                controls=[
                    filter_button("Todos", "todos"),
                    filter_button("Pendientes", "pendiente"),
                    filter_button("En proceso", "en_proceso"),
                    filter_button("Lanzados", "lanzado"),
                    filter_button("Errores", "error"),
                    filter_button("Presentados", "completado"),
                    filter_button("Cancelados", "cancelado"),
                ],
                spacing=8,
                wrap=True,
            ),
        ]

        if state["message"]:
            controls.append(state["message"])

        if not items:
            controls.append(empty_state("No hay expedientes en esta cola"))
        else:
            controls.extend(queue_card(item) for item in items)

        return ft.Column(
            controls=controls,
            spacing=18,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )

    load()
    content_area.content = build_content()
    return content_area
