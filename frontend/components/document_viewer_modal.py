from pathlib import Path
import asyncio

import flet as ft

from backend.services import document_viewer_service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest
from frontend.components.app_button import primary_button, secondary_button


Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"


def _zoomed_preview_image(image_path, page_idx, zoom):
    zoomed_width = int(700 * float(zoom or 1.6))
    viewport_width = 920
    canvas_width = max(viewport_width, zoomed_width)

    return ft.Row(
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                width=canvas_width,
                alignment=ft.alignment.Alignment(0, 0),
                content=ft.Image(
                    src=image_path,
                    width=zoomed_width,
                ),
            )
        ],
    )


def open_document_viewer_modal(
    page: ft.Page,
    file_path: str,
    title: str = "",
    expediente_id=None,
    initial_page: int = 1,
    initial_zoom: float = 1.6,
    queue=None,
    queue_index: int = 0,
    *,
    dialog=None,
    on_error=None,
    toolbar_actions=None,
    near_window: int = 3,
):
    """
    Visor documental reutilizable usando el patrón estable de Expedientes:
    AlertDialog añadido a page.overlay + ft.Image(src=preview_path).

    Incluye:
    - navegación por páginas;
    - zoom;
    - cola de documentos;
    - carga progresiva de PDF multipágina al hacer scroll.

    Devuelve el diálogo. ``dialog`` permite reutilizar un overlay del caller;
    ``on_error`` conserva su manejo de errores de apertura. ``toolbar_actions``
    recibe un PreviewRequest actual y devuelve controles de comandos; las
    operaciones PDF deben delegarse a los servicios document_tools existentes.
    ``near_window`` limita las paginas vecinas a cada lado (por defecto, tres).
    """

    viewer_queue = queue or []
    try:
        current_queue_index = int(queue_index or 0)
    except Exception:
        current_queue_index = 0

    if viewer_queue:
        current_queue_index = max(0, min(current_queue_index, len(viewer_queue) - 1))

    owns_dialog = dialog is None
    dialog = dialog if dialog is not None else ft.AlertDialog(modal=True)
    if isinstance(dialog.data, DocumentPreviewSession):
        dialog.data.close()
    session = DocumentPreviewSession(near_window=near_window)
    dialog.content = None
    dialog.actions = []
    dialog.data = session

    closed = False
    modern_dialog = owns_dialog and callable(getattr(page, "show_dialog", None))
    coordinator = session.state_lock
    running = False
    pending = None
    logical_request = PreviewRequest(str(file_path), expediente_id, initial_page, initial_zoom)
    active_view = None

    def dispose(e=None, *, pop_owned=False):
        nonlocal closed, pending
        with coordinator:
            if closed or dialog.data is not session:
                return
            closed = True
            pending = None
            session.close()
            if pop_owned and modern_dialog:
                page.pop_dialog()
            dialog.open = False
            dialog.content = None
            dialog.actions = []
            if owns_dialog and dialog in page.overlay:
                page.overlay.remove(dialog)

    def close_dialog(e=None):
        if closed or dialog.data is not session:
            return
        # Close is lifecycle work, never conditional on render publication.
        dispose(e, pop_owned=True)
        page.update()

    def open_with_system(e=None, p=file_path):
        if closed or dialog.data is not session:
            return
        try:
            document_viewer_service.open_document(str(p), expediente_id=expediente_id)
        except Exception as exc:
            if on_error:
                on_error(str(exc))

    dialog.on_dismiss = dispose

    def show(path_value, title_value=None, page_number=1, zoom=1.6, q=None, idx=0, scroll_offset=None):
        nonlocal logical_request, active_view, pending
        with coordinator:
            if closed or dialog.data is not session:
                return
            session.on_target = None
            pending = None
            logical_request = PreviewRequest(str(path_value), expediente_id, page_number, zoom)
            generation = session.invalidate()

        def render_page(path, expediente_id=None, page_number=1, zoom=1.6):
            return session.render_window(PreviewRequest(str(path), expediente_id, page_number, zoom), generation)

        built = False
        def publish_preview(preview, token):
            nonlocal logical_request, active_view, built
            if token != generation:
                return
            with session.publication(generation) as current:
                if not current:
                    return
                controls = [
                    ft.Text(str(title_value or Path(str(path_value)).name), weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK),
                    ft.Text(str(path_value), size=11, color=Q_MUTED, selectable=True),
                ]

                preview_path = preview.get("preview_path") or ""
                current_page = int(preview.get("page_number") or page_number or 1)
                total_pages = int(preview.get("total_pages") or 1)
                current_zoom = float(preview.get("zoom") or zoom or 1.6)
                preview_type = preview.get("preview_type") or ""
                logical_request = PreviewRequest(str(path_value), expediente_id, current_page, current_zoom)

                local_queue = q or []
                try:
                    local_idx = int(idx or 0)
                except Exception:
                    local_idx = 0

                if local_queue:
                    local_idx = max(0, min(local_idx, len(local_queue) - 1))

                # Fixed-height page slots preserve scroll geometry when images are evicted.
                slot_height = int(1000 * current_zoom) + 48

                def window_controls():
                    numbers = session.requested_window
                    if not numbers:
                        return []
                    result = [ft.Container(height=(numbers[0] - 1) * slot_height)]
                    for number in numbers:
                        loaded = session.loaded_window.get(number, {})
                        image_path = loaded.get("preview_path")
                        result.append(ft.Container(
                            height=slot_height,
                            content=ft.Column(controls=[
                                ft.Text(f"Página {number} de {total_pages}", size=12, color=Q_PRIMARY_DARK),
                                ft.Container(height=slot_height - 48, content=(
                                    _zoomed_preview_image(image_path, number, current_zoom)
                                    if image_path else ft.Text("No se pudo cargar esta página.")
                                )),
                            ]),
                        ))
                    result.append(ft.Container(height=(total_pages - numbers[-1]) * slot_height))
                    return result

                restoring = True
                def publish_window(preview, token):
                    if not session.is_current(token) or active_view is not list_view:
                        return
                    list_view.controls = window_controls()
                    indicator.value = f"P\u00e1gina {logical_request.page_number} de {total_pages}"
                    refresh_commands(token)
                    page.update()

                def on_viewer_scroll(e):
                    nonlocal running, pending, logical_request, restoring
                    if closed or dialog.data is not session or active_view is not list_view or preview_type != "pdf":
                        return
                    try:
                        pixels = max(0, float(getattr(e, "pixels", 0) or 0))
                        target = min(total_pages, int(pixels // slot_height) + 1)
                    except (TypeError, ValueError, OverflowError):
                        return
                    # Metrics/lifecycle notifications are not user scroll updates.
                    event_type = getattr(e, "event_type", "")
                    kind = str(getattr(event_type, "value", event_type) or "").lower()
                    if kind and kind not in ("update", "scrollupdate", "scrollnotificationtype.update"):
                        return
                    delta = getattr(e, "scroll_delta", None)
                    if pixels == 0 and logical_request.page_number > 1 and not delta and (restoring or kind):
                        return
                    restoring = False
                    with coordinator:
                        if closed or dialog.data is not session or active_view is not list_view:
                            return
                        if target == logical_request.page_number:
                            return
                        logical_request = PreviewRequest(str(path_value), expediente_id, target, current_zoom)
                        token = session.invalidate()
                        pending = (logical_request, token)
                        if running:
                            return
                        running = True
                    if callable(getattr(page, "run_task", None)):
                        async def run_pipeline():
                            await asyncio.to_thread(drain_scroll)
                        page.run_task(run_pipeline)
                    else:
                        drain_scroll()

                def drain_scroll():
                    nonlocal pending, running
                    try:
                        while True:
                            with coordinator:
                                work, pending = pending, None
                                if work is None or closed:
                                    running = False
                                    return
                            request, token = work
                            try:
                                value = session.render_window(request, token)
                            except Exception as exc:
                                # A failed obsolete target must not strand the
                                # newest pending request or stop this worker.
                                with session.publication(token) as valid:
                                    if valid:
                                        if on_error:
                                            on_error(str(exc))
                                        else:
                                            indicator.value = str(exc)
                                            page.update()
                                continue
                            with session.publication(token) as valid:
                                if valid and session.on_target:
                                    session.on_target(value, token)
                    except Exception as exc:
                        with coordinator:
                            running = False
                        if on_error:
                            on_error(str(exc))
                        else:
                            raise

                indicator = ft.Text(f"P\u00e1gina {current_page} de {total_pages}", size=12, color=Q_MUTED)

                if total_pages > 1:
                    controls.append(indicator)

                if preview.get("ok") and preview_path:
                    preview_controls = [
                        ft.Text(f"Zoom: {current_zoom:.1f}x", size=11, color=Q_MUTED),
                    ]

                    if total_pages > 1 and preview_type == "pdf":
                        preview_controls = window_controls()
                    else:
                        preview_controls.append(
                            _zoomed_preview_image(preview_path, current_page, current_zoom)
                        )

                    list_view = ft.ListView(
                        controls=preview_controls,
                        spacing=0,
                        expand=True,
                        auto_scroll=False,
                        on_scroll=on_viewer_scroll,
                    )

                    active_view = list_view
                    session.on_target = publish_window
                    controls.append(
                        ft.Container(
                            expand=True,
                            bgcolor="#F8FAFC",
                            border_radius=12,
                            border=ft.Border.all(1, Q_BORDER),
                            padding=8,
                            content=list_view,
                        )
                    )
                else:
                    controls.append(
                        ft.Container(
                            padding=16,
                            bgcolor="#FFF7ED",
                            border_radius=12,
                            border=ft.Border.all(1, "#FED7AA"),
                            content=ft.Text(
                                preview.get("message") or "No hay preview disponible para este documento.",
                                color="#9A3412",
                            ),
                        )
                    )

                if not session.is_current(generation):
                    return

                dialog.title = ft.Text("Visor documental", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)
                new_content = ft.Container(
                    width=980,
                    height=680,
                    content=ft.Column(
                        controls=controls,
                        spacing=10,
                        expand=True,
                    ),
                )

                if dialog.content is None:
                    dialog.content = new_content
                else:
                    dialog.content.content = new_content.content

                custom_count = 0
                def refresh_commands(token):
                    nonlocal custom_count
                    commands = list(toolbar_actions(logical_request) or []) if toolbar_actions and preview.get("ok") else []
                    for action in commands:
                        callback = getattr(action, "on_click", None)
                        if callback:
                            def guarded_command(event, callback=callback):
                                if dialog.data is session and session.is_current(token):
                                    callback(event)
                            action.on_click = guarded_command
                    dialog.actions[:custom_count] = commands
                    custom_count = len(commands)
                actions = []

                if local_queue and len(local_queue) > 1:
                    if local_idx > 0:
                        prev_doc = local_queue[local_idx - 1]
                        actions.append(
                            secondary_button(
                                "Doc anterior",
                                lambda e, d=prev_doc, q=local_queue, i=local_idx - 1: show(
                                    d.get("path"),
                                    d.get("name"),
                                    1,
                                    current_zoom,
                                    q,
                                    i,
                                ),
                            )
                        )

                    if local_idx < len(local_queue) - 1:
                        next_doc = local_queue[local_idx + 1]
                        actions.append(
                            primary_button(
                                "Doc siguiente",
                                lambda e, d=next_doc, q=local_queue, i=local_idx + 1: show(
                                    d.get("path"),
                                    d.get("name"),
                                    1,
                                    current_zoom,
                                    q,
                                    i,
                                ),
                            )
                        )

                if total_pages > 1:
                    if total_pages > 1:
                        actions.append(
                            secondary_button(
                                "Anterior",
                                lambda e, p=path_value, t=title_value, q=local_queue, i=local_idx: show(
                                    p, t, max(1, logical_request.page_number - 1), logical_request.zoom, q, i
                                ),
                            )
                        )

                    if total_pages > 1:
                        actions.append(
                            primary_button(
                                "Siguiente",
                                lambda e, p=path_value, t=title_value, q=local_queue, i=local_idx: show(
                                    p, t, min(total_pages, logical_request.page_number + 1), logical_request.zoom, q, i
                                ),
                            )
                        )

                if preview.get("ok") and preview_path:
                    actions.append(
                        secondary_button(
                            "Zoom -",
                            lambda e, p=path_value, t=title_value, q=local_queue, i=local_idx: show(
                                p, t, logical_request.page_number, max(0.8, logical_request.zoom - 0.4), q, i
                            ),
                        )
                    )
                    actions.append(
                        primary_button(
                            "Zoom +",
                            lambda e, p=path_value, t=title_value, q=local_queue, i=local_idx: show(
                                p, t, logical_request.page_number, min(3.5, logical_request.zoom + 0.4), q, i
                            ),
                        )
                    )

                actions.extend(
                    [
                        secondary_button("Abrir con visor del sistema", lambda e, p=path_value: open_with_system(e, p)),
                        secondary_button("Cerrar", close_dialog),
                    ]
                )

                dialog.actions = actions
                refresh_commands(generation)

                if modern_dialog:
                    if not dialog.open:
                        page.show_dialog(dialog)
                else:
                    if dialog not in page.overlay:
                        page.overlay.append(dialog)
                    dialog.open = True
                page.update()
                if preview.get("ok") and preview_type == "pdf" and total_pages > 1:
                    async def restore_scroll():
                        if session.is_current(generation):
                            await list_view.scroll_to(offset=(
                                scroll_offset if scroll_offset is not None
                                else (current_page - 1) * slot_height
                            ))
                    if callable(getattr(page, "run_task", None)):
                        page.run_task(restore_scroll)

            built = True

        session.on_target = publish_preview
        try:
            preview = render_page(
                path_value,
                expediente_id=expediente_id,
                page_number=page_number,
                zoom=zoom,
            )
        except Exception as exc:
            if not session.is_current(generation):
                return
            if on_error:
                with session.publication(generation) as current:
                    if current:
                        on_error(str(exc))
                return
            preview = {
                "ok": False,
                "preview_path": "",
                "message": str(exc),
                "page_number": 1,
                "total_pages": 1,
                "zoom": zoom,
                "preview_type": "",
            }

        if not session.is_current(generation):
            return

        if built:
            with session.publication(generation) as valid:
                if valid and session.on_target:
                    session.on_target(preview, generation)
        else:
            publish_preview(preview, generation)

    show(file_path, title, initial_page, initial_zoom, viewer_queue, current_queue_index)

    return dialog
