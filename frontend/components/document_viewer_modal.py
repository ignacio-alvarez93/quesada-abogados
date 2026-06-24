import os
from pathlib import Path

import flet as ft

from backend.services import document_viewer_service
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
):
    """
    Visor documental reutilizable usando el patrón estable de Expedientes:
    AlertDialog añadido a page.overlay + ft.Image(src=preview_path).

    Incluye:
    - navegación por páginas;
    - zoom;
    - cola de documentos;
    - carga progresiva de PDF multipágina al hacer scroll.
    """

    viewer_queue = queue or []
    try:
        current_queue_index = int(queue_index or 0)
    except Exception:
        current_queue_index = 0

    if viewer_queue:
        current_queue_index = max(0, min(current_queue_index, len(viewer_queue) - 1))

    dialog = ft.AlertDialog(modal=True)

    viewer_scroll_state = {}
    viewer_scroll_controls = {}
    viewer_scroll_loading = {}

    def close_dialog(e=None):
        dialog.open = False
        page.update()

    def open_with_system(e=None, p=file_path):
        try:
            os.startfile(str(p))
        except Exception:
            pass

    def show(path_value, title_value=None, page_number=1, zoom=1.6, q=None, idx=0):
        try:
            preview = document_viewer_service.create_document_preview(
                path_value,
                expediente_id=expediente_id,
                page_number=page_number,
                zoom=zoom,
            )
        except Exception as exc:
            preview = {
                "ok": False,
                "preview_path": "",
                "message": str(exc),
                "page_number": 1,
                "total_pages": 1,
                "zoom": zoom,
                "preview_type": "",
            }

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

        scroll_key = f"{path_value}|{current_zoom:.1f}"
        loaded_until_page = current_page

        if total_pages > 1 and preview_type == "pdf":
            try:
                loaded_until_page = int(viewer_scroll_state.get(scroll_key) or 0)
            except Exception:
                loaded_until_page = 0

            loaded_until_page = max(loaded_until_page, current_page + 3)
            loaded_until_page = min(total_pages, max(1, loaded_until_page))
            viewer_scroll_state[scroll_key] = loaded_until_page

        def page_controls(page_idx, page_preview_path):
            return [
                ft.Container(
                    padding=ft.padding.only(top=8, bottom=2),
                    content=ft.Text(
                        f"Página {page_idx} de {total_pages}",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=Q_PRIMARY_DARK,
                    ),
                ),
                _zoomed_preview_image(page_preview_path, page_idx, current_zoom),
                ft.Divider(),
            ]

        def load_more_pages(e=None):
            if not (total_pages > 1 and preview_type == "pdf"):
                return

            if viewer_scroll_loading.get(scroll_key):
                return

            current_loaded = int(viewer_scroll_state.get(scroll_key) or loaded_until_page or current_page)
            if current_loaded >= total_pages:
                return

            viewer_list = viewer_scroll_controls.get(scroll_key)
            if not viewer_list:
                return

            viewer_scroll_loading[scroll_key] = True
            try:
                new_loaded = min(total_pages, current_loaded + 3)

                for page_idx in range(current_loaded + 1, new_loaded + 1):
                    try:
                        page_preview = document_viewer_service.create_document_preview(
                            path_value,
                            expediente_id=expediente_id,
                            page_number=page_idx,
                            zoom=current_zoom,
                        )
                        page_preview_path = page_preview.get("preview_path") or ""
                    except Exception:
                        page_preview_path = ""

                    if page_preview_path:
                        viewer_list.controls.extend(page_controls(page_idx, page_preview_path))

                viewer_scroll_state[scroll_key] = new_loaded

                if new_loaded >= total_pages:
                    viewer_list.controls.append(
                        ft.Text("Documento completo cargado.", size=11, color=Q_MUTED)
                    )

                page.update()
            finally:
                viewer_scroll_loading[scroll_key] = False

        def on_viewer_scroll(e):
            try:
                pixels = float(getattr(e, "pixels", 0) or 0)
                max_scroll = float(getattr(e, "max_scroll_extent", 0) or 0)
            except Exception:
                return

            if max_scroll > 0 and pixels >= max_scroll - 250:
                load_more_pages()

        if total_pages > 1:
            controls.append(
                ft.Text(
                    f"Página {current_page} de {total_pages}",
                    size=12,
                    color=Q_MUTED,
                )
            )

        if preview.get("ok") and preview_path:
            preview_controls = [
                ft.Text(f"Zoom: {current_zoom:.1f}x", size=11, color=Q_MUTED),
            ]

            if total_pages > 1 and preview_type == "pdf":
                preview_controls.append(
                    ft.Text(
                        f"Vista rápida: páginas 1-{loaded_until_page} de {total_pages}. "
                        + ("Desplázate al final para cargar más." if loaded_until_page < total_pages else "Documento completo cargado."),
                        size=11,
                        color=Q_MUTED,
                    )
                )

                for page_idx in range(1, loaded_until_page + 1):
                    try:
                        if page_idx == current_page:
                            page_preview_path = preview_path
                        else:
                            page_preview = document_viewer_service.create_document_preview(
                                path_value,
                                expediente_id=expediente_id,
                                page_number=page_idx,
                                zoom=current_zoom,
                            )
                            page_preview_path = page_preview.get("preview_path") or ""
                    except Exception:
                        page_preview_path = ""

                    if page_preview_path:
                        preview_controls.extend(page_controls(page_idx, page_preview_path))
            else:
                preview_controls.append(
                    _zoomed_preview_image(preview_path, current_page, current_zoom)
                )

            list_view = ft.ListView(
                controls=preview_controls,
                spacing=6,
                expand=True,
                auto_scroll=False,
                on_scroll=on_viewer_scroll,
            )
            viewer_scroll_controls[scroll_key] = list_view

            controls.append(
                ft.Container(
                    expand=True,
                    bgcolor="#F8FAFC",
                    border_radius=12,
                    border=ft.border.all(1, Q_BORDER),
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
                    border=ft.border.all(1, "#FED7AA"),
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
            if current_page > 1:
                actions.append(
                    secondary_button(
                        "Anterior",
                        lambda e, p=path_value, t=title_value, pg=current_page - 1, z=current_zoom, q=local_queue, i=local_idx: show(
                            p, t, pg, z, q, i
                        ),
                    )
                )

            if current_page < total_pages:
                actions.append(
                    primary_button(
                        "Siguiente",
                        lambda e, p=path_value, t=title_value, pg=current_page + 1, z=current_zoom, q=local_queue, i=local_idx: show(
                            p, t, pg, z, q, i
                        ),
                    )
                )

        if preview.get("ok") and preview_path:
            actions.append(
                secondary_button(
                    "Zoom -",
                    lambda e, p=path_value, t=title_value, pg=current_page, z=max(0.8, current_zoom - 0.4), q=local_queue, i=local_idx: show(
                        p, t, pg, z, q, i
                    ),
                )
            )
            actions.append(
                primary_button(
                    "Zoom +",
                    lambda e, p=path_value, t=title_value, pg=current_page, z=min(3.5, current_zoom + 0.4), q=local_queue, i=local_idx: show(
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

        dialog.actions = actions

        if dialog not in page.overlay:
            page.overlay.append(dialog)

        dialog.open = True
        page.update()

    show(file_path, title, initial_page, initial_zoom, viewer_queue, current_queue_index)
