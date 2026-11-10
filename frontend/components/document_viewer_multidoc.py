"""DV24 multidocument viewer: document queue, groups of four and comparator tiles.

DocumentQueue is pure state (order, active document, groups). Comparator owns
one DocumentPreviewSession(near_window=0) per visible tile, so the mosaic
renders a single page per document and never keeps more than four sessions.
PDF operations stay in the caller's toolbar factory and act on the active
document only; no file operations or persistence here.

QueueDocument.key is the stable per-document reference for later phases
(P2 notes, P3 links); it never depends on the position in the queue.
"""
import math
from dataclasses import dataclass
from pathlib import Path

import flet as ft

from backend.services.document_preview_session import DocumentPreviewSession, PreviewRequest
from frontend.components.document_viewer_modal import (
    MAX_ZOOM, MIN_ZOOM, Q_BORDER, Q_MUTED, Q_PRIMARY, Q_PRIMARY_DARK, Q_TEXT, Q_WHITE,
    _command,
)


GROUP_SIZE = 4
MODE_SINGLE = "single"
MODE_COMPARE = "compare"
MODE_LABELS = {MODE_SINGLE: "Documento único", MODE_COMPARE: "Comparador 4"}

COMPARE_ZOOM = 1.0
ZOOM_STEP = 0.4

LOADING = "loading"
READY = "ready"
FAILED = "failed"

NO_PATH = "El documento no tiene ruta disponible."
NO_PREVIEW = "No hay vista previa disponible para este documento."


# ---------------------------------------------------------------------- queue


@dataclass(frozen=True)
class QueueDocument:
    index: int
    path: str
    name: str
    key: str
    source: dict


def document_key(entry, path, index):
    """Caller key when given (e.g. ``inbox:12``), else the document path."""
    explicit = str(entry.get("key") or "").strip()
    if explicit:
        return explicit
    return f"path:{Path(path)}" if path else f"position:{index}"


def normalize_queue(queue):
    documents = []
    for entry in queue or ():
        entry = dict(entry) if isinstance(entry, dict) else {"path": entry}
        index = len(documents)
        path = str(entry.get("path") or "").strip()
        name = str(entry.get("name") or "").strip() or (Path(path).name if path else "Documento sin nombre")
        documents.append(QueueDocument(index, path, name, document_key(entry, path, index), entry))
    return tuple(documents)


class DocumentQueue:
    """Order, active document and groups of four of one viewer queue."""

    def __init__(self, queue=None, active_index=0):
        self.documents = normalize_queue(queue)
        self.active_index = 0
        self.select(active_index)

    def __len__(self):
        return len(self.documents)

    @property
    def active(self):
        return self.documents[self.active_index] if self.documents else None

    def select(self, index):
        """Activate a document; out of range or invalid indexes are clamped."""
        if not self.documents:
            return False
        try:
            index = int(index or 0)
        except (TypeError, ValueError):
            index = 0
        index = max(0, min(index, len(self.documents) - 1))
        changed = index != self.active_index
        self.active_index = index
        return changed

    def can_move(self, offset):
        return bool(self.documents) and 0 <= self.active_index + offset < len(self.documents)

    def move(self, offset):
        return self.can_move(offset) and self.select(self.active_index + offset)

    @property
    def group_count(self):
        return math.ceil(len(self.documents) / GROUP_SIZE)

    @property
    def group_index(self):
        return self.active_index // GROUP_SIZE if self.documents else 0

    def group(self, group_index=None):
        group_index = self.group_index if group_index is None else group_index
        start = group_index * GROUP_SIZE
        return self.documents[start:start + GROUP_SIZE] if group_index >= 0 else ()

    def can_move_group(self, offset):
        return bool(self.documents) and 0 <= self.group_index + offset < self.group_count

    def move_group(self, offset):
        """Show another group; its first document becomes the active one."""
        if not self.can_move_group(offset):
            return False
        return self.select((self.group_index + offset) * GROUP_SIZE) or True

    @property
    def document_label(self):
        if not self.documents:
            return "Sin documentos"
        return f"Documento {self.active_index + 1} de {len(self.documents)}"

    @property
    def group_label(self):
        if not self.documents:
            return "Sin grupos"
        return f"Grupo {self.group_index + 1} de {self.group_count}"

    @property
    def group_summary(self):
        group = self.group()
        if not group:
            return "Sin documentos"
        count = f"{len(group)} documento{'s' if len(group) != 1 else ''}"
        first, last = group[0].index + 1, group[-1].index + 1
        span = f"Documento {first}" if first == last else f"Documentos {first}–{last}"
        return f"{count} · {span} de {len(self.documents)}"


# ---------------------------------------------------------------------- comparator lifecycle


class ComparatorTile:
    """Single-page preview state of one document in the visible group."""

    def __init__(self, document, page=1, zoom=COMPARE_ZOOM):
        self.document = document
        self.session = DocumentPreviewSession(near_window=0)
        self.page = max(1, int(page or 1))
        self.zoom = float(zoom or COMPARE_ZOOM)
        self.total_pages = 1
        self.preview_path = ""
        self.preview_type = ""
        self.message = ""
        self.status = LOADING

    @property
    def ready(self):
        return self.status == READY

    @property
    def live(self):
        return self.session.is_current(self.session.generation)

    def apply(self, result):
        result = result or {}
        if result.get("ok") and result.get("preview_path"):
            self.status = READY
            self.preview_path = str(result["preview_path"])
            self.preview_type = result.get("preview_type") or ""
            self.page = int(result.get("page_number") or self.page or 1)
            self.total_pages = int(result.get("total_pages") or 1)
            self.message = ""
        else:
            self.status = FAILED
            self.preview_path = ""
            self.preview_type = result.get("preview_type") or ""
            self.message = result.get("message") or NO_PREVIEW


class Comparator:
    """Tiles of the active document's group; never more than GROUP_SIZE sessions.

    Every group change bumps ``generation``: results of abandoned groups are
    dropped and their sessions are cancelled. Detached PreviewResources are
    returned to the caller, which closes them after the UI flush.
    """

    def __init__(self, queue, expediente_id=None, zoom=COMPARE_ZOOM):
        self.queue = queue
        self.expediente_id = expediente_id
        self.zoom = zoom
        self.tiles = []
        self.generation = 0
        self.closed = False
        # Page and zoom per queue position: plain numbers, nothing rendered.
        self.positions = {}

    def live_sessions(self):
        return sum(1 for tile in self.tiles if tile.live)

    def tile_for(self, index):
        return next((tile for tile in self.tiles if tile.document.index == index), None)

    @property
    def active_tile(self):
        return self.tile_for(self.queue.active_index)

    def remember(self, index, page=None, zoom=None):
        known_page, known_zoom = self.positions.get(index, (1, self.zoom))
        self.positions[index] = (page or known_page, zoom or known_zoom)

    def _detach(self):
        resources = []
        for tile in self.tiles:
            self.remember(tile.document.index, tile.page, tile.zoom)
            released = tile.session.cancel()
            if released is not None:
                resources.append(released)
        self.tiles = []
        return resources

    def open_group(self):
        """New tiles for the active group; returns (generation, detached resources)."""
        if self.closed:
            return self.generation, []
        self.generation += 1
        resources = self._detach()
        self.tiles = [ComparatorTile(document, *self.positions.get(document.index, (1, self.zoom)))
                      for document in self.queue.group()]
        return self.generation, resources

    def suspend(self):
        """Leave the mosaic (single mode); the comparator can open groups again."""
        self.generation += 1
        return self._detach()

    def cancel(self):
        self.closed = True
        return self.suspend()

    def adjust(self, tile, page_offset=0, zoom_delta=0.0):
        """Change one tile's page or zoom within bounds; True when it must re-render."""
        if not tile.ready:
            return False
        page = max(1, min(tile.total_pages, tile.page + page_offset))
        zoom = round(max(MIN_ZOOM, min(MAX_ZOOM, tile.zoom + zoom_delta)), 2)
        if (page, zoom) == (tile.page, tile.zoom):
            return False
        tile.page, tile.zoom, tile.status = page, zoom, LOADING
        return True

    def render(self, tile, generation, publication, publish):
        """Render one page for one tile; publish only while tile and group are current.

        ``publication()`` is the shell's context manager: it yields whether the
        viewer is live and serializes this publication against close.
        A failure stays inside its tile; the rest of the group is unaffected.
        """
        if generation != self.generation or tile not in self.tiles:
            return False
        tile_generation = tile.session.invalidate()
        if not tile.document.path:
            result = {"ok": False, "message": NO_PATH}
        else:
            request = PreviewRequest(tile.document.path, self.expediente_id, tile.page, tile.zoom)
            try:
                result = tile.session.render_window(request, tile_generation)
            except Exception as exc:
                result = {"ok": False, "message": str(exc) or NO_PREVIEW}
        with publication() as live:
            if not (live and generation == self.generation and tile in self.tiles
                    and tile.session.is_current(tile_generation)):
                return False
            tile.apply(result)
            self.remember(tile.document.index, tile.page, tile.zoom)
            publish()
            return True


def close_resources(resources):
    """Disk cleanup after the UI flush; leftovers stay namespaced on failure."""
    for item in resources:
        if item is None:
            continue
        try:
            item.close()
        except OSError:
            pass


# ---------------------------------------------------------------------- Flet builders


def strip_height(metrics):
    return 42 if metrics.compact else 48


def queue_command(label, on_click, *, icon, metrics, disabled=False, tooltip=None,
                  trailing_icon=False):
    """Clearly visible queue/group arrow, sized for the mode strip."""
    return _command(label, on_click, icon=icon, width=metrics.nav_width + 40,
                    height=strip_height(metrics) - 6, disabled=disabled, tooltip=tooltip,
                    trailing_icon=trailing_icon)


def mode_strip(metrics, mode, *, on_single, on_compare, center, summary):
    """Mode selector, queue/group navigation and a short summary.

    Returns (container, mode buttons). The current mode is the highlighted,
    inert button; the other one switches mode.
    """
    height = strip_height(metrics) - 6
    buttons = []
    for value, icon, handler in ((MODE_SINGLE, ft.Icons.DESCRIPTION_OUTLINED, on_single),
                                 (MODE_COMPARE, ft.Icons.GRID_VIEW, on_compare)):
        selected = value == mode
        button = _command(MODE_LABELS[value], None if selected else handler, icon=icon,
                          primary=selected, width=metrics.open_width, height=height,
                          tooltip="Modo actual." if selected else None)
        button.data = f"mode:{value}"
        buttons.append(button)
    summary_text = ft.Text(summary, size=12, color=Q_MUTED, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.RIGHT)
    container = ft.Container(
        height=strip_height(metrics),
        content=ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    padding=2, border_radius=10, bgcolor="#F1F5F9",
                    border=ft.Border.all(1, Q_BORDER),
                    content=ft.Row(buttons, spacing=2, tight=True),
                ),
                ft.Container(expand=True),
                *center,
                ft.Container(expand=True),
                summary_text,
            ],
        ),
    )
    return container, buttons


def position_label(text, metrics):
    """Boxed indicator between two arrows, e.g. ``Documento 2 de 5``."""
    return ft.Container(
        width=metrics.nav_width + 32,
        alignment=ft.Alignment(0, 0),
        content=text,
    )


def _tile_button(icon, tooltip, on_click, disabled, reason=None):
    button = ft.IconButton(icon=icon, icon_size=18, icon_color=Q_PRIMARY_DARK,
                           tooltip=reason if disabled and reason else tooltip,
                           on_click=None if disabled else on_click)
    button.disabled = disabled
    button.data = tooltip
    return button


class TileView:
    """Controls of one comparator tile: header, independent commands and preview.

    DV24-P3: ``selection`` (checked, on_change) adds a checkbox for the
    multi-selection, independent of the active document; the active marker
    then becomes a radio mark so both states stay distinguishable.
    """

    def __init__(self, tile, active, width, height, *, on_select, on_page, on_zoom, selection=None):
        index = tile.document.index
        self.tile = tile
        self.index = index
        self.active = active
        ready = tile.ready
        self.name = ft.Text(tile.document.name, size=13, weight=ft.FontWeight.W_600, color=Q_TEXT,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=tile.document.path)
        self.page_label = ft.Text(
            f"Página {tile.page} de {tile.total_pages}" if ready else "Página —",
            size=12, color=Q_PRIMARY_DARK)
        self.zoom_label = ft.Text(f"{tile.zoom:.1f}x" if ready else "—", size=12, color=Q_MUTED)
        single = "El documento tiene una sola página."
        self.previous_page = _tile_button(
            ft.Icons.CHEVRON_LEFT, "Página anterior", lambda e: on_page(index, -1),
            not ready or tile.page <= 1, single if ready and tile.total_pages < 2 else None)
        self.next_page = _tile_button(
            ft.Icons.CHEVRON_RIGHT, "Página siguiente", lambda e: on_page(index, 1),
            not ready or tile.page >= tile.total_pages,
            single if ready and tile.total_pages < 2 else None)
        self.zoom_out = _tile_button(
            ft.Icons.REMOVE, "Zoom -", lambda e: on_zoom(index, -ZOOM_STEP),
            not ready or tile.zoom <= MIN_ZOOM)
        self.zoom_in = _tile_button(
            ft.Icons.ADD, "Zoom +", lambda e: on_zoom(index, ZOOM_STEP),
            not ready or tile.zoom >= MAX_ZOOM)
        self.buttons = [self.previous_page, self.next_page, self.zoom_out, self.zoom_in]

        self.checkbox = None
        leading = []
        if selection is None:
            marker = ft.Icon(ft.Icons.CHECK_BOX if active else ft.Icons.INSERT_DRIVE_FILE_OUTLINED,
                             size=20, color=Q_PRIMARY if active else Q_MUTED)
        else:
            checked, on_change = selection
            self.checkbox = ft.Checkbox(value=bool(checked), on_change=on_change,
                                        data=tile.document.key)
            leading.append(self.checkbox)
            marker = ft.Icon(ft.Icons.RADIO_BUTTON_CHECKED if active else ft.Icons.RADIO_BUTTON_UNCHECKED,
                             size=18, color=Q_PRIMARY if active else Q_MUTED)
        header = ft.Container(
            height=40,
            content=ft.Row(
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[*leading, marker, ft.Container(expand=True, content=self.name),
                          self.page_label, self.zoom_label, *self.buttons],
            ),
        )
        inner_width = max(120, width - 16)
        body_height = max(80, height - 16 - 40 - 6)
        self.body = self._body(inner_width, body_height)
        self.container = ft.Container(
            width=width,
            height=height,
            padding=8,
            border_radius=12,
            bgcolor="#F5F9FF" if active else Q_WHITE,
            border=ft.Border.all(2 if active else 1, Q_PRIMARY if active else Q_BORDER),
            on_click=lambda e: on_select(index),
            data=tile.document.key,
            content=ft.Column(spacing=6, controls=[header, self.body]),
        )

    def _body(self, width, height):
        tile = self.tile
        if tile.status == LOADING:
            return ft.Container(
                height=height, alignment=ft.Alignment(0, 0), bgcolor="#E8EEF6", border_radius=8,
                content=ft.Column(tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                  controls=[ft.ProgressRing(width=24, height=24),
                                            ft.Text("Cargando vista previa…", size=12, color=Q_MUTED)]),
            )
        if tile.status == FAILED:
            return ft.Container(
                height=height, padding=12, alignment=ft.Alignment(0, 0), bgcolor="#FFF7ED",
                border_radius=8, border=ft.Border.all(1, "#FED7AA"),
                content=ft.Text(tile.message, color="#9A3412", text_align=ft.TextAlign.CENTER),
            )
        image_width = int((width - 16) * tile.zoom)
        return ft.Container(
            height=height, bgcolor="#E8EEF6", border_radius=8, padding=8,
            content=ft.Column(scroll=ft.ScrollMode.AUTO, controls=[
                ft.Row(scroll=ft.ScrollMode.AUTO, alignment=ft.MainAxisAlignment.CENTER, controls=[
                    ft.Image(src=tile.preview_path, width=image_width),
                ]),
            ]),
        )


def _empty_slot(width, height):
    return ft.Container(
        width=width, height=height, border_radius=12, bgcolor="#F8FAFC",
        border=ft.Border.all(1, Q_BORDER), alignment=ft.Alignment(0, 0),
        content=ft.Text("Grupo incompleto: no hay más documentos en la cola.",
                        size=12, color=Q_MUTED, text_align=ft.TextAlign.CENTER),
    )


def comparator_grid(comparator, width, height, *, on_select, on_page, on_zoom, gap=10,
                    selection=None):
    """Responsive mosaic: one row for up to two documents, else 2x2.

    ``selection(document)`` returns a tile's (checked, on_change) for the
    DV24-P3 multi-selection; None keeps the P1 tiles.
    Returns (control, tile views in queue order).
    """
    tiles = list(comparator.tiles)
    if not tiles:
        return ft.Container(
            height=height, alignment=ft.Alignment(0, 0), bgcolor="#F8FAFC", border_radius=12,
            content=ft.Text("No hay documentos en este grupo.", color=Q_MUTED),
        ), []
    rows = 1 if len(tiles) <= 2 else 2
    columns = 1 if len(tiles) == 1 else 2
    tile_width = (width - gap * (columns - 1)) // columns
    tile_height = (height - gap * (rows - 1)) // rows
    active = comparator.queue.active_index
    views = [TileView(tile, tile.document.index == active, tile_width, tile_height,
                      on_select=on_select, on_page=on_page, on_zoom=on_zoom,
                      selection=selection(tile.document) if selection else None)
             for tile in tiles]
    cells = [view.container for view in views]
    cells += [_empty_slot(tile_width, tile_height) for _ in range(rows * columns - len(cells))]
    grid = ft.Column(spacing=gap, controls=[
        ft.Row(cells[row * columns:(row + 1) * columns], spacing=gap)
        for row in range(rows)
    ])
    return ft.Container(height=height, content=grid), views
