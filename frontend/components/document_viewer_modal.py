import inspect
import threading
from pathlib import Path

import flet as ft

from backend.services import document_viewer_service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest
from frontend.components.app_button import primary_button, secondary_button


Q_PRIMARY_DARK = "#003B7A"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"

_VIEWER_DISMISS = object()


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


def _contains(controls, control):
    return any(item is control for item in controls or ())


def _dialog_stack(page):
    """Dialogs opened with page.show_dialog (Flet >= 0.80); None if unknown."""
    controls = getattr(getattr(page, "_dialogs", None), "controls", None)
    return controls if isinstance(controls, list) else None


def _present_dialog(page, dialog):
    """Show once: reuse a registered overlay/stack entry, else show_dialog or overlay."""
    dialog.open = True
    stack = _dialog_stack(page)
    if _contains(page.overlay, dialog) or (stack is not None and _contains(stack, dialog)):
        page.update()
        return
    show_dialog = getattr(page, "show_dialog", None)
    if callable(show_dialog):
        try:
            show_dialog(dialog)
            return
        except RuntimeError:
            # Flet reports an already opened dialog; keep that instance.
            page.update()
            return
    page.overlay.append(dialog)
    page.update()


def _request_dismiss(page, dialog):
    """Close only this dialog: pop it when it is on top, never another one."""
    stack = _dialog_stack(page)
    pop_dialog = getattr(page, "pop_dialog", None)
    if callable(pop_dialog) and stack and stack[-1] is dialog:
        try:
            pop_dialog()
            return
        except Exception:
            pass
    dialog.open = False


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
    AlertDialog + ft.Image(src=preview_path). Usa page.show_dialog/pop_dialog
    cuando existen y page.overlay como fallback; un diálogo ya registrado por
    la vista se reutiliza sin moverlo ni eliminarlo.

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
    # Navigation counter: scroll callbacks of a replaced shell become inert.
    viewer = {"navigation": 0}

    def finish(dismissed):
        nonlocal closed
        with session.publication(session.generation) as current:
            if not current or closed or dialog.data is not session:
                return False
            closed = True
            # close() never waits for native rendering; obsolete work is discarded.
            session.close()
            if dismissed:
                dialog.open = False
            else:
                _request_dismiss(page, dialog)
            dialog.content = None
            dialog.actions = []
            if owns_dialog and _contains(page.overlay, dialog):
                page.overlay.remove(dialog)
            page.update()
            return True

    def close_dialog(e=None):
        finish(dismissed=False)

    # Preserve a caller's dismiss handler without chaining older viewer sessions.
    previous_dismiss = dialog.on_dismiss
    if getattr(previous_dismiss, "_viewer_marker", None) is _VIEWER_DISMISS:
        previous_dismiss = previous_dismiss._viewer_previous

    def on_dialog_dismiss(e=None):
        if dialog.data is not session:
            return
        finish(dismissed=True)
        if previous_dismiss:
            previous_dismiss(e)

    on_dialog_dismiss._viewer_marker = _VIEWER_DISMISS
    on_dialog_dismiss._viewer_previous = previous_dismiss
    dialog.on_dismiss = on_dialog_dismiss

    def open_with_system(e=None, p=file_path):
        if closed or dialog.data is not session:
            return
        try:
            document_viewer_service.open_document(str(p), expediente_id=expediente_id)
        except Exception as exc:
            if on_error:
                on_error(str(exc))

    def show(path_value, title_value=None, page_number=1, zoom=1.6, q=None, idx=0):
        if closed or dialog.data is not session:
            return
        with session.publication(session.generation) as live:
            if not live:
                return
            viewer["navigation"] += 1
            navigation = viewer["navigation"]
            generation = session.invalidate()

        try:
            preview = session.render_window(
                PreviewRequest(str(path_value), expediente_id, page_number, zoom), generation)
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

            def build_actions(shown_page, action_generation):
                # Optional command factory receives the current document, never a stale
                # initial queue item. PDF operations remain in document_tools services.
                actions = list(toolbar_actions(PreviewRequest(
                    str(path_value), expediente_id, shown_page, current_zoom,
                )) or []) if toolbar_actions and preview.get("ok") else []
                # Commands from replaced pages, queue items or closed viewers are stale.
                for action in actions:
                    callback = getattr(action, "on_click", None)
                    if callback:
                        def guarded_command(event, callback=callback):
                            if dialog.data is session and session.is_current(action_generation):
                                callback(event)
                        action.on_click = guarded_command

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
                    if shown_page > 1:
                        actions.append(
                            secondary_button(
                                "Anterior",
                                lambda e, p=path_value, t=title_value, pg=shown_page - 1, z=current_zoom, q=local_queue, i=local_idx: show(
                                    p, t, pg, z, q, i
                                ),
                            )
                        )

                    if shown_page < total_pages:
                        actions.append(
                            primary_button(
                                "Siguiente",
                                lambda e, p=path_value, t=title_value, pg=shown_page + 1, z=current_zoom, q=local_queue, i=local_idx: show(
                                    p, t, pg, z, q, i
                                ),
                            )
                        )

                if preview.get("ok") and preview_path:
                    actions.append(
                        secondary_button(
                            "Zoom -",
                            lambda e, p=path_value, t=title_value, pg=shown_page, z=max(0.8, current_zoom - 0.4), q=local_queue, i=local_idx: show(
                                p, t, pg, z, q, i
                            ),
                        )
                    )
                    actions.append(
                        primary_button(
                            "Zoom +",
                            lambda e, p=path_value, t=title_value, pg=shown_page, z=min(3.5, current_zoom + 0.4), q=local_queue, i=local_idx: show(
                                p, t, pg, z, q, i
                            ),
                        )
                    )

                actions.extend(
                    [
                        secondary_button("Abrir con visor del sistema", lambda e, p=path_value: open_with_system(e, p)),
                        secondary_button("Cerrar", close_dialog),
                    ]
                )
                return actions

            # Latest-target-wins: one drain loop per shell renders the newest
            # target; events arriving meanwhile only replace that target.
            scroll = {"target": current_page, "page": current_page, "failed": None, "busy": False}
            scroll_lock = threading.Lock()

            def publish_scroll_target(target):
                with session.publication(session.generation) as live:
                    if not live or dialog.data is not session or viewer["navigation"] != navigation:
                        return "stale"
                    window_generation = session.invalidate()
                try:
                    window = session.render_window(
                        PreviewRequest(str(path_value), expediente_id, target, current_zoom),
                        window_generation,
                        superseded=lambda: scroll["target"] != target,
                    )
                except Exception:
                    return "failed" if session.is_current(window_generation) else "stale"
                with session.publication(window_generation) as live:
                    if not live or viewer["navigation"] != navigation:
                        return "stale"
                    if not window.get("ok"):
                        return "failed"
                    shown_page = int(window.get("page_number") or target)
                    with scroll_lock:
                        scroll["page"] = target
                    # Patch the window in place: same ListView, same total
                    # extent, so the user's scroll offset is never restored late.
                    page_label.value = f"Página {shown_page} de {total_pages}"
                    list_view.controls = window_controls()
                    dialog.actions = build_actions(shown_page, window_generation)
                    page.update()
                return "ok"

            def on_viewer_scroll(e):
                if (closed or dialog.data is not session or viewer["navigation"] != navigation
                        or preview_type != "pdf" or total_pages < 2):
                    return
                try:
                    pixels = max(0, float(getattr(e, "pixels", 0) or 0))
                    target = min(total_pages, int(pixels // slot_height) + 1)
                except (TypeError, ValueError, OverflowError):
                    return
                with scroll_lock:
                    scroll["target"] = target
                    if scroll["busy"]:
                        return
                    scroll["busy"] = True
                try:
                    while True:
                        with scroll_lock:
                            target = scroll["target"]
                            if target in (scroll["page"], scroll["failed"]):
                                scroll["busy"] = False
                                return
                        outcome = publish_scroll_target(target)
                        if outcome == "stale":
                            return
                        with scroll_lock:
                            scroll["failed"] = target if outcome == "failed" else None
                            if outcome == "failed":
                                # The shell's commands are stale now; any other
                                # target, including the shown page, republishes.
                                scroll["page"] = None
                finally:
                    with scroll_lock:
                        scroll["busy"] = False

            page_label = ft.Text(
                f"Página {current_page} de {total_pages}",
                size=12,
                color=Q_MUTED,
            )
            if total_pages > 1:
                controls.append(page_label)

            list_view = None
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

            dialog.title = ft.Text("Visor documental", weight=ft.FontWeight.BOLD, color=Q_PRIMARY_DARK)
            dialog.content = ft.Container(
                width=980,
                height=680,
                content=ft.Column(
                    controls=controls,
                    spacing=10,
                    expand=True,
                ),
            )
            dialog.actions = build_actions(current_page, generation)

            _present_dialog(page, dialog)
            if preview.get("ok") and preview_type == "pdf" and total_pages > 1:
                async def restore_scroll():
                    # Runs once per shell; any later scroll or navigation makes it obsolete.
                    if session.is_current(generation):
                        result = list_view.scroll_to(offset=(current_page - 1) * slot_height)
                        if inspect.isawaitable(result):
                            await result
                if callable(getattr(page, "run_task", None)):
                    page.run_task(restore_scroll)

    show(file_path, title, initial_page, initial_zoom, viewer_queue, current_queue_index)

    return dialog
