import inspect
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import flet as ft

from backend.services import document_viewer_service
from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest


Q_PRIMARY = "#0057B8"
Q_PRIMARY_DARK = "#003B7A"
Q_NAVY = "#0A2647"
Q_TEXT = "#1E293B"
Q_MUTED = "#64748B"
Q_BORDER = "#D0D5DD"
Q_CANVAS = "#E8EEF6"
Q_WHITE = "#FFFFFF"

_VIEWER_DISMISS = object()

# Approved DV23 target resolutions; every one must fit without clipped buttons.
SUPPORTED_VIEWPORTS = ((1366, 768), (1600, 900), (1920, 1080))

MIN_ZOOM = 0.8
MAX_ZOOM = 3.5

# Icons for the PDF tools; labels come from the toolbar factory.
_TOOL_ICONS = {
    "rotate": ft.Icons.ROTATE_RIGHT,
    "move_page": ft.Icons.OPEN_WITH,
    "split": ft.Icons.CALL_SPLIT,
    "compress": ft.Icons.FILE_DOWNLOAD,
    "extract": ft.Icons.OUTPUT,
    "merge": ft.Icons.LIBRARY_ADD,
    "annotate": ft.Icons.EDIT_NOTE,
}


@dataclass(frozen=True)
class ViewerMetrics:
    """Pixel budget of the viewer shell for one window size.

    Widths are fixed so the toolbar's required width can be checked against
    the available width for each supported resolution.
    """
    viewport: tuple
    compact: bool
    inset_h: int
    inset_v: int
    outer_width: int
    header_height: int
    info_height: int
    canvas_height: int
    tile_width: int
    tile_height: int
    tile_gap: int
    nav_width: int
    zoom_width: int
    open_width: int
    close_width: int
    separator_margin: int

    CONTENT_PAD = 20
    GROUP_TITLE = 16
    TOOLBAR_PAD = 10
    # Paddings and spacing around content and actions, plus a safety margin.
    CHROME = 12 + 10 + 10 + 14 + 12

    @property
    def content_width(self):
        return self.outer_width - 2 * self.CONTENT_PAD

    @property
    def toolbar_height(self):
        return self.tile_height + self.GROUP_TITLE + 6 + 2 * self.TOOLBAR_PAD

    @property
    def total_height(self):
        return (self.header_height + self.info_height + self.canvas_height
                + self.toolbar_height + self.CHROME)

    def toolbar_width(self, tools):
        groups = [
            2 * self.nav_width + 8,
            2 * self.zoom_width + 8,
            self.open_width + 8 + self.close_width,
        ]
        if tools:
            groups.insert(0, tools * self.tile_width + (tools - 1) * self.tile_gap)
        separators = (len(groups) - 1) * (1 + 2 * self.separator_margin)
        # Container padding and its 1 px border on both sides.
        return sum(groups) + separators + 2 * 12 + 2


def viewer_metrics(width, height):
    compact = width < 1500 or height < 860
    inset_h, inset_v = (16, 10) if compact else (40, 24)
    outer_width = max(720, min(width - 2 * inset_h, 1600))
    header, info = (60, 36) if compact else (72, 42)
    metrics = dict(
        viewport=(width, height), compact=compact, inset_h=inset_h, inset_v=inset_v,
        outer_width=outer_width, header_height=header, info_height=info, canvas_height=0,
        tile_width=64 if compact else 78, tile_height=56 if compact else 64,
        tile_gap=6 if compact else 8, nav_width=108 if compact else 120,
        zoom_width=92 if compact else 104, open_width=148 if compact else 168,
        close_width=84 if compact else 96, separator_margin=10 if compact else 14,
    )
    shell = ViewerMetrics(**metrics)
    available = min(height - 2 * inset_v, 980)
    metrics["canvas_height"] = max(240, available - (shell.total_height - shell.canvas_height))
    return ViewerMetrics(**metrics)


def _viewport(page):
    for source in (page, getattr(page, "window", None)):
        width = getattr(source, "width", None)
        height = getattr(source, "height", None)
        if (isinstance(width, (int, float)) and isinstance(height, (int, float))
                and width > 0 and height > 0):
            return int(width), int(height)
    # Unknown size: the smallest supported screen always fits.
    return SUPPORTED_VIEWPORTS[0]


class ViewerLayout:
    """Stable references to the semantic controls of one viewer shell."""

    def __init__(self, metrics, title, path, page_label, zoom_label, queue_label, canvas):
        self.metrics = metrics
        self.title = title
        self.path = path
        self.page_label = page_label
        self.zoom_label = zoom_label
        self.queue_label = queue_label
        self.canvas = canvas
        self.buttons = []
        # DV24: mode strip and comparator; ``document`` is the active
        # QueueDocument, the stable per-document reference for notes/links.
        self.mode = "single"
        self.mode_buttons = []
        self.group_label = None
        self.tiles = []
        self.queue = None
        self.comparator = None
        self.document = None
        # DV24-P2: NotesController of the active document; None without notes.
        self.notes = None


def viewer_layout(dialog):
    """ViewerLayout of an open viewer; None once it is closed."""
    data = getattr(getattr(dialog, "content", None), "data", None)
    return data if isinstance(data, ViewerLayout) else None


def viewer_active_document(dialog):
    """QueueDocument (index, path, name, key) of the active document; None if closed."""
    layout = viewer_layout(dialog)
    return layout.document if layout else None


def viewer_action_label(control):
    """Visible label of a viewer command, whatever its visual composition."""
    content = getattr(control, "content", None)
    if isinstance(content, ft.Text):
        return content.value
    for child in getattr(content, "controls", None) or ():
        if isinstance(child, ft.Text):
            return child.value
    return None


def viewer_action_buttons(dialog):
    """Commands in their historical order: PDF tools, queue, pages, zoom, exit."""
    layout = viewer_layout(dialog)
    return list(layout.buttons) if layout else []


def _zoomed_preview_image(image_path, page_idx, zoom, viewport_width=920):
    zoomed_width = int(700 * float(zoom or 1.6))
    canvas_width = max(viewport_width, zoomed_width)

    return ft.Row(
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Container(
                width=canvas_width,
                alignment=ft.Alignment(0, 0),
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


def _flush(page, dialog):
    """Patch only the dialog subtree when Flet has mounted it.

    page.update() diffs the whole CRM page; a registered, mounted dialog
    only needs its own subtree. Unmounted dialogs fall back to the page.
    """
    stack = _dialog_stack(page)
    if _contains(page.overlay, dialog) or (stack is not None and _contains(stack, dialog)):
        try:
            dialog.update()
            return
        except RuntimeError:
            pass  # Not mounted by a Flet session.
    page.update()


def _present_dialog(page, dialog):
    """Show once: reuse a registered overlay/stack entry, else show_dialog or overlay."""
    dialog.open = True
    stack = _dialog_stack(page)
    if _contains(page.overlay, dialog) or (stack is not None and _contains(stack, dialog)):
        _flush(page, dialog)
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


def _command(label, on_click, *, icon=None, primary=False, width=None, height=42,
             tooltip=None, disabled=False, trailing_icon=False):
    """Toolbar button; disabled commands keep their label and explain why."""
    color = Q_WHITE if primary and not disabled else (Q_MUTED if disabled else Q_PRIMARY_DARK)
    text = ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=color,
                   text_align=ft.TextAlign.CENTER, max_lines=2)
    parts = [text]
    if icon:
        glyph = ft.Icon(icon, size=18, color=color)
        parts = [text, glyph] if trailing_icon else [glyph, text]
    style = ft.ButtonStyle(
        bgcolor=(Q_PRIMARY if primary and not disabled else Q_WHITE),
        side=ft.BorderSide(1, Q_PRIMARY if primary and not disabled else Q_BORDER),
        shape=ft.RoundedRectangleBorder(radius=8),
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
    )
    button = ft.OutlinedButton(
        content=ft.Row(parts, spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
        on_click=None if disabled else on_click,
        width=width,
        height=height,
        style=style,
        tooltip=tooltip,
    )
    button.disabled = disabled
    return button


def _tool_tile(control, metrics):
    """Re-skin a toolbar factory command as an icon-over-label tile.

    Callback, disabled state, tooltip and data stay those of the factory.
    """
    label = viewer_action_label(control) or ""
    disabled = bool(getattr(control, "disabled", False))
    color = Q_MUTED if disabled else Q_PRIMARY_DARK
    icon = _TOOL_ICONS.get(getattr(control, "data", None), ft.Icons.PICTURE_AS_PDF_OUTLINED)
    control.content = ft.Column(
        tight=True,
        spacing=2,
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(icon, size=20, color=color),
            ft.Text(label, size=10.5 if metrics.compact else 11, weight=ft.FontWeight.W_600,
                    color=color, text_align=ft.TextAlign.CENTER, max_lines=2),
        ],
    )
    control.width = metrics.tile_width
    control.height = metrics.tile_height
    control.style = ft.ButtonStyle(
        bgcolor=Q_WHITE,
        side=ft.BorderSide(1, Q_BORDER),
        shape=ft.RoundedRectangleBorder(radius=8),
        padding=ft.Padding.symmetric(horizontal=2, vertical=4),
    )
    return control


def _group(title, icon, controls, gap, metrics):
    heading = [ft.Text(title, size=10.5, weight=ft.FontWeight.W_700, color=Q_NAVY)] if title else []
    if title and icon:
        heading.insert(0, ft.Icon(icon, size=14, color=Q_NAVY))
    return ft.Column(
        tight=True,
        spacing=6,
        controls=[
            ft.Container(height=metrics.GROUP_TITLE, content=ft.Row(heading, spacing=6)),
            ft.Row(controls, spacing=gap, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ],
    )


def _separator(metrics):
    return ft.Container(
        width=1,
        height=metrics.tile_height + metrics.GROUP_TITLE,
        bgcolor=Q_BORDER,
        margin=ft.Margin.symmetric(horizontal=metrics.separator_margin),
    )


def _header(name_text, metrics, on_close):
    return ft.Container(
        width=metrics.outer_width,
        height=metrics.header_height,
        padding=ft.Padding.symmetric(horizontal=20),
        border_radius=ft.BorderRadius.only(top_left=16, top_right=16),
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, 0),
            end=ft.Alignment(1, 0),
            colors=[Q_NAVY, "#0B3B7A", "#0A2E5C"],
        ),
        content=ft.Row(
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    width=40, height=40, bgcolor="#1D6FD8", border_radius=10,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, color=Q_WHITE, size=22),
                ),
                ft.Text("Visor documental", size=18 if metrics.compact else 22,
                        weight=ft.FontWeight.BOLD, color=Q_WHITE),
                ft.Container(width=1, height=28, bgcolor="#FFFFFF55"),
                ft.Container(expand=True, content=name_text),
                ft.Row(spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Icon(ft.Icons.BALANCE, color=Q_WHITE, size=26),
                    ft.Column(spacing=0, tight=True, controls=[
                        ft.Text("Quesada Abogados", size=13, weight=ft.FontWeight.BOLD, color=Q_WHITE),
                        ft.Text("CRM / ERP", size=10, color="#C7D2FE"),
                    ]),
                ]),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=Q_WHITE,
                    tooltip="Cerrar visor",
                    on_click=on_close,
                    style=ft.ButtonStyle(
                        side=ft.BorderSide(1, "#FFFFFF66"),
                        shape=ft.RoundedRectangleBorder(radius=8),
                    ),
                ),
            ],
        ),
    )


def _info_separator():
    return ft.Container(width=1, height=22, bgcolor=Q_BORDER,
                        margin=ft.Margin.symmetric(horizontal=8))


def _info_row(metrics, path_text, page_label, zoom_label, extra=()):
    """Path, page and zoom of the shown (or active) document."""
    return ft.Container(
        height=metrics.info_height,
        border=ft.Border(bottom=ft.BorderSide(1, Q_BORDER)),
        content=ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.FOLDER_OUTLINED, size=18, color=Q_MUTED),
                ft.Container(expand=True, content=path_text),
                *extra,
                _info_separator(),
                ft.Icon(ft.Icons.INSERT_DRIVE_FILE_OUTLINED, size=18, color=Q_PRIMARY_DARK),
                page_label,
                _info_separator(),
                ft.Icon(ft.Icons.SEARCH, size=18, color=Q_PRIMARY_DARK),
                zoom_label,
            ],
        ),
    )


def _toolbar_row(metrics, tools, navigation, zoom, exits, navigation_title="NAVEGACIÓN"):
    """Grouped DV23 toolbar: edition, navigation, zoom, exit at the right edge."""
    groups = []
    if tools:
        groups.append(_group("EDICIÓN Y PROCESAMIENTO DEL PDF", ft.Icons.LAYERS_OUTLINED,
                             tools, metrics.tile_gap, metrics))
    groups += [
        _group(navigation_title, ft.Icons.SWAP_HORIZ, navigation, 8, metrics),
        _group("ZOOM", ft.Icons.ZOOM_IN, zoom, 8, metrics),
    ]
    row = []
    for group in groups:
        if row:
            row.append(_separator(metrics))
        row.append(group)
    # The exit group sits at the right edge, as in the approved design.
    spare = max(0, metrics.content_width - metrics.toolbar_width(len(tools)))
    row += [_separator(metrics), ft.Container(width=spare), _group("", None, exits, 8, metrics)]
    return ft.Container(
        width=metrics.content_width,
        padding=ft.Padding.symmetric(horizontal=12, vertical=metrics.TOOLBAR_PAD),
        border=ft.Border.all(1, Q_BORDER),
        border_radius=12,
        bgcolor="#F8FAFC",
        # Fixed widths fit every supported resolution; scrolling only
        # protects smaller windows from clipped commands.
        content=ft.Row(row, spacing=0, scroll=ft.ScrollMode.AUTO,
                       vertical_alignment=ft.CrossAxisAlignment.END),
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
    notes=None,
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

    Diseño DV23: cabecera (``dialog.title``), fila de ruta/página/zoom y
    lienzo (``dialog.content``), y barra agrupada de Edición, Navegación,
    Zoom y salida (``dialog.actions``). viewer_layout() y
    viewer_action_buttons() exponen los controles semánticos.

    Devuelve el diálogo. ``dialog`` permite reutilizar un overlay del caller;
    ``on_error`` conserva su manejo de errores de apertura. ``toolbar_actions``
    recibe un PreviewRequest actual y devuelve controles de comandos; las
    operaciones PDF deben delegarse a los servicios document_tools existentes.
    ``near_window`` limita las paginas vecinas a cada lado (por defecto, tres).

    DV24: con una cola de dos o más documentos aparece una franja con el
    selector ``Documento único`` / ``Comparador 4`` y las flechas de
    documento (o de grupo), separada de la página y del zoom. El comparador
    muestra el grupo de cuatro del documento activo, una página por documento;
    las herramientas PDF actúan solo sobre el documento activo.

    DV24-P2: ``notes`` (ViewerNotes de la vista, con el usuario autenticado)
    añade a la derecha del lienzo el panel plegable ``Notas y actividad`` del
    documento activo, en modo único y en el comparador. Sin ``notes`` el
    visor es el de DV23/P1.
    """
    # Lazy import: the multidoc module reuses this module's style helpers.
    from frontend.components import document_viewer_multidoc as multidoc

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

    metrics = viewer_metrics(*_viewport(page))
    dialog.title_padding = ft.Padding.all(0)
    dialog.content_padding = ft.Padding.only(left=metrics.CONTENT_PAD, right=metrics.CONTENT_PAD,
                                             top=12, bottom=10)
    dialog.actions_padding = ft.Padding.only(left=metrics.CONTENT_PAD, right=metrics.CONTENT_PAD,
                                             bottom=14)
    dialog.inset_padding = ft.Padding.symmetric(horizontal=metrics.inset_h, vertical=metrics.inset_v)
    dialog.shape = ft.RoundedRectangleBorder(radius=16)
    dialog.clip_behavior = ft.ClipBehavior.ANTI_ALIAS
    dialog.bgcolor = Q_WHITE

    closed = False
    # Navigation counter: scroll callbacks of a replaced shell become inert.
    # ``shell`` versions comparator shells; their PDF commands go stale with it.
    viewer = {"navigation": 0, "mode": multidoc.MODE_SINGLE, "shell": 0,
              "single_zoom": initial_zoom}
    # Without a queue the opened document is the only (active) one.
    queue_model = multidoc.DocumentQueue(
        viewer_queue or [{"path": str(file_path), "name": title}], current_queue_index)
    multi = len(viewer_queue) > 1
    comparator = multidoc.Comparator(queue_model, expediente_id)
    strip_space = multidoc.strip_height(metrics) + 10 if multi else 0
    canvas_height = metrics.canvas_height - strip_space

    def notes_publication(apply):
        """Notes panel updates: applied and flushed only while this viewer is live."""
        with session.publication(session.generation) as live:
            if not live or closed or dialog.data is not session:
                return False
            if apply():
                _flush(page, dialog)
            return True

    def notes_resized():
        # Under the publication lock: the mosaic re-lays out its tiles; the
        # single-mode canvas just takes the width the panel frees.
        if viewer["mode"] == multidoc.MODE_COMPARE:
            publish_compare()

    notes_panel = None
    if notes is not None:
        from frontend.components.document_viewer_notes_panel import NotesController
        notes_panel = NotesController(notes, expediente_id=expediente_id, compact=metrics.compact,
                                      publish=notes_publication, on_resize=notes_resized)

    def notes_space():
        return notes_panel.space if notes_panel is not None else 0

    def finish(dismissed):
        """Visual close first; disk cleanup after the UI flush, off the lock.

        Under the publication lock: mark closed, cancel the session and the
        comparator tiles (no I/O, no wait for native rendering), dismiss and
        detach the shell, flush once. Then delete their preview PNGs.
        """
        nonlocal closed
        with session.publication(session.generation) as current:
            if not current or closed or dialog.data is not session:
                return False
            closed = True
            resources = session.cancel()
            tile_resources = comparator.cancel()
            if notes_panel is not None:
                notes_panel.close()
            if dismissed:
                dialog.open = False
            else:
                _request_dismiss(page, dialog)
            dialog.content = None
            dialog.actions = []
            if owns_dialog and _contains(page.overlay, dialog):
                page.overlay.remove(dialog)
                page.update()
            else:
                _flush(page, dialog)
        # The dialog is already closed; leftovers stay namespaced.
        multidoc.close_resources([resources, *tile_resources])
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
            # Single mode: the mosaic's sessions are released, never kept alive.
            viewer["mode"] = multidoc.MODE_SINGLE
            viewer["shell"] += 1
            tile_resources = comparator.suspend()
        multidoc.close_resources(tile_resources)

        try:
            if multi and not str(path_value or "").strip():
                raise FileNotFoundError(multidoc.NO_PATH)
            preview = session.render_window(
                PreviewRequest(str(path_value), expediente_id, page_number, zoom), generation)
        except Exception as exc:
            if not session.is_current(generation):
                return
            # Opening reports to the caller; a queue step keeps the viewer and
            # shows the failure for that document instead.
            if on_error and (navigation == 1 or not multi):
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
            name = str(title_value or Path(str(path_value)).name)
            preview_path = preview.get("preview_path") or ""
            current_page = int(preview.get("page_number") or page_number or 1)
            total_pages = int(preview.get("total_pages") or 1)
            current_zoom = float(preview.get("zoom") or zoom or 1.6)
            preview_type = preview.get("preview_type") or ""
            has_preview = bool(preview.get("ok") and preview_path)

            local_queue = q or []
            try:
                local_idx = int(idx or 0)
            except Exception:
                local_idx = 0

            if local_queue:
                local_idx = max(0, min(local_idx, len(local_queue) - 1))
                queue_model.select(local_idx)
            viewer["single_zoom"] = current_zoom

            # Fixed-height page slots preserve scroll geometry when images are evicted.
            slot_height = int(1000 * current_zoom) + 48
            image_viewport = metrics.content_width - 16 - notes_space()

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
                                _zoomed_preview_image(image_path, number, current_zoom, image_viewport)
                                if image_path else ft.Text("No se pudo cargar esta página.")
                            )),
                        ]),
                    ))
                result.append(ft.Container(height=(total_pages - numbers[-1]) * slot_height))
                return result

            def go(page_target, zoom_target):
                return lambda e: show(path_value, title_value, page_target, zoom_target,
                                      local_queue, local_idx)

            def queue_commands():
                if not local_queue or len(local_queue) <= 1:
                    return []
                commands = []
                for label, offset, icon, reason, hint in (
                    ("Doc anterior", -1, ft.Icons.ARROW_BACK, "Es el primer documento de la cola.",
                     "Documento anterior de la cola"),
                    ("Doc siguiente", 1, ft.Icons.ARROW_FORWARD, "Es el último documento de la cola.",
                     "Documento siguiente de la cola"),
                ):
                    target = local_idx + offset
                    available = 0 <= target < len(local_queue)
                    doc = queue_model.documents[target] if available else None
                    # DV24: visible arrows in the mode strip, apart from pages and zoom.
                    commands.append(multidoc.queue_command(
                        label,
                        lambda e, d=doc, i=target: show(
                            d.path, d.name, 1, current_zoom, local_queue, i),
                        icon=icon, metrics=metrics, disabled=not available,
                        tooltip=hint if available else reason,
                        trailing_icon=offset > 0,
                    ))
                return commands

            queue_buttons = queue_commands()

            def build_toolbar(shown_page, action_generation):
                # Optional command factory receives the current document, never a stale
                # initial queue item. PDF operations remain in document_tools services.
                tools = list(toolbar_actions(PreviewRequest(
                    str(path_value), expediente_id, shown_page, current_zoom,
                )) or []) if toolbar_actions and preview.get("ok") else []
                # Commands from replaced pages, queue items or closed viewers are stale.
                for action in tools:
                    callback = getattr(action, "on_click", None)
                    if callback:
                        def guarded_command(event, callback=callback):
                            if dialog.data is session and session.is_current(action_generation):
                                callback(event)
                        action.on_click = guarded_command
                    _tool_tile(action, metrics)

                single = "El documento tiene una sola página."
                previous_page = _command(
                    "Anterior", go(shown_page - 1, current_zoom), icon=ft.Icons.CHEVRON_LEFT,
                    width=metrics.nav_width, disabled=total_pages < 2 or shown_page <= 1,
                    tooltip=single if total_pages < 2 else (
                        "Ya estás en la primera página." if shown_page <= 1 else None),
                )
                next_page = _command(
                    "Siguiente", go(shown_page + 1, current_zoom), icon=ft.Icons.CHEVRON_RIGHT,
                    primary=True, width=metrics.nav_width,
                    disabled=total_pages < 2 or shown_page >= total_pages,
                    tooltip=single if total_pages < 2 else (
                        "Ya estás en la última página." if shown_page >= total_pages else None),
                )
                no_preview = "No hay vista previa para ampliar."
                zoom_out = _command(
                    "Zoom -", go(shown_page, max(MIN_ZOOM, current_zoom - 0.4)), icon=ft.Icons.REMOVE,
                    width=metrics.zoom_width, disabled=not has_preview or current_zoom <= MIN_ZOOM,
                    tooltip=no_preview if not has_preview else (
                        "Zoom mínimo alcanzado." if current_zoom <= MIN_ZOOM else None),
                )
                zoom_in = _command(
                    "Zoom +", go(shown_page, min(MAX_ZOOM, current_zoom + 0.4)), icon=ft.Icons.ADD,
                    width=metrics.zoom_width, disabled=not has_preview or current_zoom >= MAX_ZOOM,
                    tooltip=no_preview if not has_preview else (
                        "Zoom máximo alcanzado." if current_zoom >= MAX_ZOOM else None),
                )
                external = _command(
                    "Abrir con visor del sistema", lambda e, p=path_value: open_with_system(e, p),
                    icon=ft.Icons.OPEN_IN_NEW, width=metrics.open_width,
                )
                close_button = _command("Cerrar", close_dialog, width=metrics.close_width)
                close_button.style.bgcolor = "#E2E8F0"

                layout.buttons = tools + queue_buttons + mode_buttons + [
                    previous_page, next_page, zoom_out, zoom_in, external, close_button]
                return _toolbar_row(metrics, tools, [previous_page, next_page],
                                    [zoom_out, zoom_in], [external, close_button])

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
                    dialog.actions = [build_toolbar(shown_page, window_generation)]
                    _flush(page, dialog)
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

            page_label = ft.Text(f"Página {current_page} de {total_pages}", size=13,
                                 weight=ft.FontWeight.W_600, color=Q_TEXT)
            zoom_label = ft.Text(f"Zoom: {current_zoom:.1f}x" if has_preview else "Zoom: —",
                                 size=13, weight=ft.FontWeight.W_600, color=Q_TEXT)
            queue_label = ft.Text(
                f"Documento {local_idx + 1} de {len(local_queue)}" if len(local_queue) > 1 else "",
                size=13, weight=ft.FontWeight.W_700, color=Q_NAVY, visible=len(local_queue) > 1,
            )
            path_text = ft.Text(str(path_value), size=12, color=Q_TEXT, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS, tooltip=str(path_value))
            title_text = ft.Text(name, size=14 if metrics.compact else 16, color=Q_WHITE,
                                 weight=ft.FontWeight.W_500, max_lines=1,
                                 overflow=ft.TextOverflow.ELLIPSIS, tooltip=name)

            list_view = None
            if has_preview:
                if total_pages > 1 and preview_type == "pdf":
                    preview_controls = window_controls()
                else:
                    preview_controls = [
                        _zoomed_preview_image(preview_path, current_page, current_zoom, image_viewport)]

                list_view = ft.ListView(
                    controls=preview_controls,
                    spacing=0,
                    expand=True,
                    auto_scroll=False,
                    on_scroll=on_viewer_scroll,
                )
                canvas = ft.Container(
                    height=canvas_height,
                    bgcolor=Q_CANVAS,
                    border_radius=12,
                    border=ft.Border.all(1, Q_BORDER),
                    padding=8,
                    content=list_view,
                )
            else:
                canvas = ft.Container(
                    height=canvas_height,
                    padding=16,
                    bgcolor="#FFF7ED",
                    border_radius=12,
                    border=ft.Border.all(1, "#FED7AA"),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(
                        preview.get("message") or "No hay preview disponible para este documento.",
                        color="#9A3412",
                    ),
                )

            # DV24: queue arrows live in their own strip, apart from page and zoom.
            info_row = _info_row(metrics, path_text, page_label, zoom_label)
            canvas_area = canvas
            if notes_panel is not None:
                canvas_area = notes_panel.beside(canvas, queue_model.active, canvas_height)
            shell_controls = [info_row, canvas_area]
            mode_buttons = []
            strip = None
            if multi:
                strip, mode_buttons = multidoc.mode_strip(
                    metrics, multidoc.MODE_SINGLE, on_single=None, on_compare=show_compare,
                    center=[queue_buttons[0], multidoc.position_label(queue_label, metrics),
                            queue_buttons[1]],
                    summary=f"{len(local_queue)} documentos en cola")
                shell_controls.insert(0, strip)

            layout = ViewerLayout(metrics, title_text, path_text, page_label, zoom_label,
                                  queue_label, canvas)
            layout.mode_buttons = mode_buttons
            layout.queue = queue_model
            layout.comparator = comparator
            layout.document = queue_model.active
            layout.notes = notes_panel
            dialog.title = _header(title_text, metrics, close_dialog)
            dialog.content = ft.Container(
                width=metrics.content_width,
                height=strip_space + metrics.info_height + 10 + canvas_height,
                data=layout,
                content=ft.Column(
                    controls=shell_controls,
                    spacing=10,
                ),
            )
            dialog.actions = [build_toolbar(current_page, generation)]

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

    # ------------------------------------------------------------------ DV24 comparator

    @contextmanager
    def compare_publication():
        """Live comparator shell, serialized against navigation and close."""
        with session.publication(session.generation) as live:
            yield (live and not closed and dialog.data is session
                   and viewer["mode"] == multidoc.MODE_COMPARE)

    def render_group(generation):
        # One page per tile in queue order; an abandoned group stops here.
        for tile in list(comparator.tiles):
            if generation != comparator.generation:
                return
            comparator.render(tile, generation, compare_publication, publish_compare)

    def show_compare(e=None):
        if closed or dialog.data is not session or len(queue_model) < 2:
            return
        with session.publication(session.generation) as live:
            if not live or closed or viewer["mode"] == multidoc.MODE_COMPARE:
                return
            # Single-mode scroll callbacks and restores become inert; its
            # window PNGs are released so only the mosaic's sessions remain.
            viewer["navigation"] += 1
            shown = session.current_request
            if shown is not None:
                comparator.remember(queue_model.active_index, page=shown.page_number)
            released = session.release()
            viewer["mode"] = multidoc.MODE_COMPARE
            generation, detached = comparator.open_group()
            publish_compare()
        multidoc.close_resources([released, *detached])
        render_group(generation)

    def show_single(e=None):
        if closed or dialog.data is not session or viewer["mode"] != multidoc.MODE_COMPARE:
            return
        active = queue_model.active
        tile = comparator.tile_for(active.index)
        page_number = tile.page if tile is not None else comparator.positions.get(active.index, (1,))[0]
        show(active.path, active.name, page_number, viewer["single_zoom"], viewer_queue, active.index)

    def move_group(offset):
        with compare_publication() as live:
            if not live or not queue_model.move_group(offset):
                return
            generation, detached = comparator.open_group()
            publish_compare()
        multidoc.close_resources(detached)
        render_group(generation)

    def select_tile(index):
        with compare_publication() as live:
            if live and comparator.tile_for(index) is not None and queue_model.select(index):
                publish_compare()

    def tile_command(index, page_offset=0, zoom_delta=0.0):
        """Page or zoom of one tile; the tile becomes the active document."""
        with compare_publication() as live:
            tile = comparator.tile_for(index) if live else None
            if tile is None:
                return
            queue_model.select(index)
            changed = comparator.adjust(tile, page_offset, zoom_delta)
            generation = comparator.generation
            publish_compare()
        if changed:
            comparator.render(tile, generation, compare_publication, publish_compare)

    def compare_commands(active, tile, token):
        """Toolbar commands bound to the active document only."""
        ready = tile is not None and tile.ready
        tools = list(toolbar_actions(PreviewRequest(
            active.path, expediente_id, tile.page, tile.zoom,
        )) or []) if toolbar_actions and ready else []
        # Commands of a replaced shell (other active document, page or group) are stale.
        for action in tools:
            callback = getattr(action, "on_click", None)
            if callback:
                def guarded_command(event, callback=callback):
                    if dialog.data is session and not closed and viewer["shell"] == token:
                        callback(event)
                action.on_click = guarded_command
            _tool_tile(action, metrics)

        index = active.index
        no_preview = "El documento activo no tiene vista previa."
        single = "El documento tiene una sola página."
        multipage = ready and tile.total_pages > 1
        previous_page = _command(
            "Anterior", lambda e: tile_command(index, page_offset=-1), icon=ft.Icons.CHEVRON_LEFT,
            width=metrics.nav_width, disabled=not multipage or tile.page <= 1,
            tooltip=no_preview if not ready else single if not multipage else (
                "Ya estás en la primera página." if tile.page <= 1 else None),
        )
        next_page = _command(
            "Siguiente", lambda e: tile_command(index, page_offset=1), icon=ft.Icons.CHEVRON_RIGHT,
            primary=True, width=metrics.nav_width,
            disabled=not multipage or tile.page >= tile.total_pages,
            tooltip=no_preview if not ready else single if not multipage else (
                "Ya estás en la última página." if tile.page >= tile.total_pages else None),
        )
        zoom_out = _command(
            "Zoom -", lambda e: tile_command(index, zoom_delta=-multidoc.ZOOM_STEP),
            icon=ft.Icons.REMOVE, width=metrics.zoom_width,
            disabled=not ready or tile.zoom <= MIN_ZOOM,
            tooltip=no_preview if not ready else (
                "Zoom mínimo alcanzado." if tile.zoom <= MIN_ZOOM else None),
        )
        zoom_in = _command(
            "Zoom +", lambda e: tile_command(index, zoom_delta=multidoc.ZOOM_STEP),
            icon=ft.Icons.ADD, width=metrics.zoom_width,
            disabled=not ready or tile.zoom >= MAX_ZOOM,
            tooltip=no_preview if not ready else (
                "Zoom máximo alcanzado." if tile.zoom >= MAX_ZOOM else None),
        )
        external = _command(
            "Abrir con visor del sistema", lambda e, p=active.path: open_with_system(e, p),
            icon=ft.Icons.OPEN_IN_NEW, width=metrics.open_width, disabled=not active.path,
            tooltip=None if active.path else multidoc.NO_PATH,
        )
        close_button = _command("Cerrar", close_dialog, width=metrics.close_width)
        close_button.style.bgcolor = "#E2E8F0"
        return tools, [previous_page, next_page], [zoom_out, zoom_in], [external, close_button]

    def publish_compare():
        """Rebuild the comparator shell from tile state; the caller holds the lock."""
        viewer["shell"] += 1
        token = viewer["shell"]
        active = queue_model.active
        tile = comparator.tile_for(active.index)
        ready = tile is not None and tile.ready

        title_text = ft.Text(active.name, size=14 if metrics.compact else 16, color=Q_WHITE,
                             weight=ft.FontWeight.W_500, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS, tooltip=active.name)
        path_text = ft.Text(active.path or multidoc.NO_PATH, size=12, color=Q_TEXT, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS, tooltip=active.path or None)
        page_label = ft.Text(f"Página {tile.page} de {tile.total_pages}" if ready else "Página —",
                             size=13, weight=ft.FontWeight.W_600, color=Q_TEXT)
        zoom_label = ft.Text(f"Zoom: {tile.zoom:.1f}x" if ready else "Zoom: —",
                             size=13, weight=ft.FontWeight.W_600, color=Q_TEXT)
        queue_label = ft.Text(f"Activo: {queue_model.document_label}", size=13,
                              weight=ft.FontWeight.W_600, color=Q_NAVY)
        group_label = ft.Text(queue_model.group_label, size=13, weight=ft.FontWeight.W_700, color=Q_NAVY)

        group_buttons = []
        for label, offset, icon, reason in (
            ("Grupo anterior", -1, ft.Icons.ARROW_BACK, "Es el primer grupo de la cola."),
            ("Grupo siguiente", 1, ft.Icons.ARROW_FORWARD, "Es el último grupo de la cola."),
        ):
            available = queue_model.can_move_group(offset)
            group_buttons.append(multidoc.queue_command(
                label, lambda e, o=offset: move_group(o), icon=icon, metrics=metrics,
                disabled=not available, tooltip=None if available else reason,
                trailing_icon=offset > 0,
            ))
        strip, mode_buttons = multidoc.mode_strip(
            metrics, multidoc.MODE_COMPARE, on_single=show_single, on_compare=None,
            center=[group_buttons[0], multidoc.position_label(group_label, metrics), group_buttons[1]],
            summary=queue_model.group_summary)
        canvas, tiles = multidoc.comparator_grid(
            comparator, metrics.content_width - notes_space(), canvas_height, on_select=select_tile,
            on_page=lambda index, offset: tile_command(index, page_offset=offset),
            on_zoom=lambda index, delta: tile_command(index, zoom_delta=delta))
        info_row = _info_row(metrics, path_text, page_label, zoom_label,
                             extra=[_info_separator(), queue_label])
        tools, navigation, zoom, exits = compare_commands(active, tile, token)
        canvas_area = canvas
        if notes_panel is not None:
            canvas_area = notes_panel.beside(canvas, active, canvas_height)

        layout = ViewerLayout(metrics, title_text, path_text, page_label, zoom_label,
                              queue_label, canvas)
        layout.mode = multidoc.MODE_COMPARE
        layout.mode_buttons = mode_buttons
        layout.group_label = group_label
        layout.tiles = tiles
        layout.queue = queue_model
        layout.comparator = comparator
        layout.document = active
        layout.notes = notes_panel
        layout.buttons = tools + group_buttons + mode_buttons + navigation + zoom + exits
        dialog.title = _header(title_text, metrics, close_dialog)
        dialog.content = ft.Container(
            width=metrics.content_width,
            height=strip_space + metrics.info_height + 10 + canvas_height,
            data=layout,
            content=ft.Column(controls=[strip, info_row, canvas_area], spacing=10),
        )
        dialog.actions = [_toolbar_row(metrics, tools, navigation, zoom, exits,
                                       navigation_title="DOCUMENTO ACTIVO")]
        _flush(page, dialog)

    show(file_path, title, initial_page, initial_zoom, viewer_queue, current_queue_index)

    return dialog
