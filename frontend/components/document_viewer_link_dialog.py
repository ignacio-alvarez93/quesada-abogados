"""DV24-P3: "Vincular a expediente" from the document viewer.

Logical link only, through document_viewer_link_service (which reuses
document_inbox_service.link_inbox_item): nothing is copied to Box, moved,
imported or created, and the viewer's notes are not touched. No SQL here.

LinkController lives as long as the viewer: link state of the active
document in the info row, and in ``Comparador 4`` a multi-selection that is
independent of the active document (PDF tools and notes keep following the
active one). LinkForm is the confirmation dialog presented above the viewer.

DV25-P3A: once an expediente is chosen, LinkForm also shows an existing
folder of its Box root and a catalog nomenclature per document, with a
preview of the proposed names (document_viewer_filing_plan_service). It is a
preview only: nothing is reserved, persisted or copied, and ``Vincular y
archivar copia`` stays disabled until P3B. ``Vincular`` is still the only
operation.

DV25-P3B2: LinkController only adds the entry point ``Archivar en Box`` (active
document) / ``Archivar seleccionados`` (comparator) to the separate archive
dialog (document_viewer_archive_dialog). LinkForm is unchanged and never
archives; the archive never changes the link selection or link state.

DV26-UI1: visual composition only. A navy header inside the content (the
DV24 ``dialog.title`` stays as the semantic title), documents and destination
on the left, the Box planning card on the right, review and confirmation and
the wide preview table below, and a status strip that never scrolls away
above the actions. Sizes come from the window (LinkLayout); the body scrolls
inside the dialog. State, services and controls are those of DV24/DV25.

DV28-FIX2: ``Vincular y archivar copia`` runs the same confirmed link as
``Vincular`` and then, only for the documents whose link was confirmed, opens
the existing archive dialog with the folder and nomenclatures chosen here
preselected. The archive keeps its own review and consent; LinkForm never
copies.
"""
import threading
from dataclasses import dataclass, replace

import flet as ft

from backend.services import document_viewer_filing_plan_service as filing_service
from backend.services import document_viewer_link_service as link_service
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.document_viewer_modal import (
    Q_BORDER, Q_MUTED, Q_NAVY, Q_PRIMARY, Q_TEXT, Q_WHITE, _command, _contains, _flush,
    _info_separator, _present_dialog, _request_dismiss, _viewport,
)


Q_SUCCESS = "#027A48"
Q_ERROR = "#B42318"
Q_WARNING = "#B54708"
Q_SURFACE = "#F8FAFC"
Q_BOX_BG = "#F0F9FF"
Q_BOX_BORDER = "#B9E6FE"

LOGICAL_ONLY = ("Vinculación lógica en el CRM: no copia a Box, no mueve, renombra ni modifica "
                "archivos y no importa documentos.")
NO_SELECTION = "Marca documentos en el comparador para vincularlos juntos."
ARCHIVE_TOOLTIP = ("Archivar una copia en la carpeta Box del expediente ya vinculado (revisión y "
                   "confirmación previas; nunca mueve ni sobrescribe).")
NO_ARCHIVE_SOURCE = "Sin documento de Bandeja: no se archiva desde el visor."
NO_ARCHIVE_SELECTION = "Marca documentos de Bandeja en el comparador para archivarlos."
ARCHIVE_AFTER_LINK = ("Vincular y archivar copia: vincula y, solo si la vinculación se confirma, abre la "
                      "revisión del archivado en Box con su propia confirmación.")
NOT_LINKED_NOT_ARCHIVED = "{count} documento(s) no se vincularon: no se archivan."

OUTCOME_COLORS = {
    link_service.READY: Q_TEXT,
    link_service.LINKED: Q_SUCCESS,
    link_service.UNCHANGED: Q_MUTED,
    link_service.TRANSFER: Q_WARNING,
    link_service.NOT_LINKABLE: Q_WARNING,
    link_service.REJECTED: Q_ERROR,
    link_service.FAILED: Q_ERROR,
}
OUTCOME_LABELS = {
    link_service.READY: "Vinculable",
    link_service.LINKED: "Vinculado",
    link_service.UNCHANGED: "Sin cambios",
    link_service.TRANSFER: "Traslado",
    link_service.NOT_LINKABLE: "No vinculable",
    link_service.REJECTED: "Rechazado",
    link_service.FAILED: "Error",
}

# DV26-UI1 texts of the Box planning card and the preview table.
BOX_TITLE = "Archivo en Box (previsualización)"
BOX_BADGE = "Planificación / sin escritura"
BOX_NO_WRITES = ("No se crea, copia, mueve, sobrescribe, renombra ni reserva ningún archivo: "
                 "solo se planifica.")
CHOOSE_EXPEDIENT = "Elige un expediente para ver sus carpetas y nomenclaturas."
PREVIEW_TITLE = "Vista previa de vinculación / archivo"
PREVIEW_PENDING = "La previsión aparece al elegir un expediente."
PREVIEW_COLUMNS = ("Origen", "Bandeja", "Nomenclatura / rol", "Subcarpeta", "Nombre propuesto", "Estado")
PREVIEW_COLORS = {
    filing_service.PROPOSED: Q_SUCCESS,
    filing_service.COLLISION: Q_WARNING,
    filing_service.BLOCKED: Q_ERROR,
}


@dataclass(frozen=True)
class LinkLayout:
    """Pixel budget of LinkForm for one window; the body scrolls inside ``height``.

    ``wide``: documents and destination on the left, Box planning on the
    right. ``pair``: width of client and expediente side by side (0 when
    they are stacked with ``field``).
    """
    width: int
    height: int
    wide: bool
    left: int
    right: int
    pair: int
    field: int
    box_field: int

    INSET_H = 16
    INSET_V = 12
    PAD = 20
    GAP = 16
    # Card padding (2 x 16) and border (2 x 1).
    CARD = 34
    # Actions row: 42 px buttons, its paddings and a safety margin.
    FOOTER = 80
    MIN_FIELD = 260


def link_layout(width, height):
    content = max(640, min(1240, width - 2 * LinkLayout.INSET_H))
    inner = content - 2 * LinkLayout.PAD
    wide = inner >= 960
    left = (inner - LinkLayout.GAP) * 11 // 20 if wide else inner
    right = inner - LinkLayout.GAP - left if wide else inner
    area = left - LinkLayout.CARD
    pair = (area - 12) // 2 if area >= 2 * LinkLayout.MIN_FIELD + 12 else 0
    return LinkLayout(
        width=content,
        height=max(420, min(900, height - 2 * LinkLayout.INSET_V - LinkLayout.FOOTER)),
        wide=wide, left=left, right=right, pair=pair, field=min(area, 560),
        box_field=min(right - LinkLayout.CARD, 560),
    )


def _badge(text, color, bgcolor):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=8, vertical=2), border_radius=10, bgcolor=bgcolor,
        content=ft.Text(text, size=10.5, weight=ft.FontWeight.W_600, color=color, max_lines=1))


def _card(title, icon, controls, *, badge=None, bgcolor=Q_WHITE, border=Q_BORDER, data=None):
    heading = [ft.Icon(icon, size=18, color=Q_PRIMARY),
               ft.Text(title, size=13, weight=ft.FontWeight.W_700, color=Q_NAVY, expand=True)]
    if badge is not None:
        heading.append(badge)
    return ft.Container(
        padding=16, border_radius=12, bgcolor=bgcolor, border=ft.Border.all(1, border), data=data,
        content=ft.Column([ft.Row(heading, spacing=8), *controls], spacing=10, tight=True))


def _banner(text, color, *, data=None):
    """Notice that must stay readable (Box notices, filing errors)."""
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=10, vertical=8), border_radius=8, bgcolor="#FFFAEB",
        border=ft.Border.all(1, "#FEDF89"),
        content=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=16, color=color),
                        ft.Text(text, size=11.5, color=color, data=data, selectable=True, expand=True)],
                       spacing=8, vertical_alignment=ft.CrossAxisAlignment.START))


def _hint(text, *, data=None):
    return ft.Text(text, size=11.5, color=Q_MUTED, italic=True, data=data)


def _positive(value):
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


@dataclass(frozen=True)
class ViewerLinking:
    """Link context a view injects into the viewer.

    ``actor`` is the authenticated session user ({"id", "username"}); the
    service verifies it. Bandeja views add (path, item id, expedient id) of
    the documents the viewer may show; documents without an item id (an
    expediente's folder) are reported as not directly linkable.
    ``on_linked(result)`` lets the view refresh its listing; ``db_path`` is
    only for isolated tests.
    """
    actor: object = None
    inbox_items: tuple = ()
    on_linked: object = None
    db_path: object = None

    def with_inbox_items(self, pairs):
        """``pairs``: (path, Bandeja item dict) of the viewable documents."""
        known = []
        for path, item in pairs or ():
            path, item = str(path or "").strip(), item or {}
            item_id = _positive(item.get("id"))
            if path and item_id:
                known.append((path, item_id, _positive(item.get("expedient_id"))))
        return replace(self, inbox_items=tuple(known))

    def _known(self, path):
        return next(((item_id, expedient_id) for known, item_id, expedient_id in self.inbox_items
                     if known == path), (None, None))

    def request(self, document):
        """Service request for a QueueDocument; the service resolves the rest."""
        path = str(getattr(document, "path", "") or "").strip()
        item_id = _positive((getattr(document, "source", None) or {}).get("inbox_item_id"))
        return {
            "key": getattr(document, "key", "") or f"path:{path}",
            "name": getattr(document, "name", "") or "Documento",
            "path": path,
            "inbox_item_id": item_id or self._known(path)[0],
        }

    def known_expedient(self, document):
        return self._known(str(getattr(document, "path", "") or "").strip())[1]


class LinkController:
    """Link commands and selection of one viewer.

    ``publish(apply)`` is the viewer's: under its publication lock, while the
    viewer is live, it runs ``apply`` and flushes when it returns True.
    ``on_change(documents)`` re-lays out the viewer's link state (and the
    notes activity of ``documents``) without touching page, zoom or group.
    """

    def __init__(self, linking, *, page, publish, on_change):
        self.linking = linking
        self.page = page
        self.publish = publish
        self.on_change = on_change
        self.closed = False
        self.form = None
        # DV25-P3B2 archive dialog; one dialog (link or archive) at a time.
        self.archive_form = None
        self.archive_button = None
        # Selection for ``Vincular seleccionados``, by stable document key.
        self.selected = {}
        # Targets linked from this viewer, by document key.
        self.linked = {}
        self.document = None
        self.status_text = None
        self.counter_text = None
        self.link_button = None
        self.selected_button = None

    @property
    def buttons(self):
        return [button for button in (self.link_button, self.selected_button, self.archive_button)
                if button is not None]

    # ------------------------------------------------------------------ viewer API

    def info_controls(self, document, *, compare, height):
        """Link state and commands for the viewer's info row."""
        self.document = document
        self.status_text = ft.Text(self.status(document), size=12, weight=ft.FontWeight.W_600,
                                   color=Q_NAVY, max_lines=1, data="link-status")
        self.link_button = _command(
            "Vincular a expediente", lambda e: self.open_active(), icon=ft.Icons.LINK,
            height=height, tooltip="Vincular el documento activo a un expediente (sin copiar a Box).")
        controls = [_info_separator(), ft.Icon(ft.Icons.LINK, size=18, color=Q_PRIMARY),
                    self.status_text, self.link_button]
        self.counter_text = self.selected_button = None
        if compare:
            count = len(self.selected)
            self.counter_text = ft.Text(f"{count} seleccionado{'s' if count != 1 else ''}", size=12,
                                        color=Q_TEXT, data="link-counter")
            self.selected_button = _command(
                "Vincular seleccionados", lambda e: self.open_selected(),
                icon=ft.Icons.PLAYLIST_ADD_CHECK, height=height, disabled=not count,
                tooltip=None if count else NO_SELECTION)
            controls += [_info_separator(), self.counter_text, self.selected_button]
        self.archive_button = self._archive_command(document, compare, height)
        return controls + [self.archive_button]

    def _archive_command(self, document, compare, height):
        """Entry point to the archive dialog; disabled without a Bandeja source."""
        if compare:
            sources = [d for d in self.selected.values() if self.linking.request(d)["inbox_item_id"]]
            return _command("Archivar seleccionados", lambda e: self.open_archive_selected(),
                            icon=ft.Icons.ARCHIVE_OUTLINED, height=height, disabled=not sources,
                            tooltip=ARCHIVE_TOOLTIP if sources else NO_ARCHIVE_SELECTION)
        source = self.linking.request(document)["inbox_item_id"] is not None
        return _command("Archivar en Box", lambda e: self.open_archive_active(),
                        icon=ft.Icons.ARCHIVE_OUTLINED, height=height, disabled=not source,
                        tooltip=ARCHIVE_TOOLTIP if source else NO_ARCHIVE_SOURCE)

    def selection(self, document):
        """(checked, on_change) of a comparator tile's checkbox."""
        def handler(e=None):
            value = getattr(getattr(e, "control", None), "value", None)
            self.toggle(document, value)
        return document.key in self.selected, handler

    def status(self, document):
        target = self.linked.get(getattr(document, "key", None))
        if target is not None:
            return f"Vinculado a {target.label}"
        if self.linking.request(document)["inbox_item_id"] is None:
            return "No vinculable directamente"
        expedient_id = self.linking.known_expedient(document)
        return f"Expediente #{expedient_id}" if expedient_id else "Sin expediente"

    def update_status(self):
        """Single mode: refresh the info row in place."""
        if self.status_text is None or self.document is None:
            return False
        self.status_text.value = self.status(self.document)
        return True

    def close(self):
        """Viewer closed: an open form is closed and late results are dropped."""
        self.closed = True
        if self.form is not None:
            self.form.close()
        if self.archive_form is not None:
            self.archive_form.close()

    # ------------------------------------------------------------------ events

    def toggle(self, document, value=None):
        def apply():
            if self.closed:
                return False
            chosen = document.key not in self.selected if value is None else bool(value)
            if chosen:
                self.selected[document.key] = document
            else:
                self.selected.pop(document.key, None)
            return self.on_change(())
        self.publish(apply)

    def open_active(self):
        if self.document is not None:
            return self._open([self.document], multiple=False)
        return None

    def open_selected(self):
        documents = sorted(self.selected.values(), key=lambda document: document.index)
        return self._open(documents, multiple=True) if documents else None

    def _busy(self):
        return self.closed or any(form is not None and not form.closed
                                  for form in (self.form, self.archive_form))

    def _open(self, documents, multiple):
        # One form at a time: a second click while it is open does nothing.
        if self._busy():
            return None
        self.form = LinkForm(self, documents, multiple=multiple).show()
        return self.form

    def open_archive_active(self):
        if self.document is not None:
            return self._open_archive([self.document], multiple=False)
        return None

    def open_archive_selected(self):
        # Snapshot of the comparator selection; the archive never changes it.
        documents = sorted(self.selected.values(), key=lambda document: document.index)
        return self._open_archive(documents, multiple=True) if documents else None

    def open_archive_linked(self, documents, *, multiple, folder, choices, notice=""):
        """DV28-FIX2: archive review of the documents just linked, with the LinkForm choices."""
        return self._open_archive(documents, multiple, folder=folder, choices=choices, notice=notice)

    def _open_archive(self, documents, multiple, **carried):
        if self._busy():
            return None
        from frontend.components.document_viewer_archive_dialog import ArchiveForm
        self.archive_form = ArchiveForm(self, documents, multiple=multiple, **carried).show()
        return self.archive_form

    def finished(self, documents, result):
        """After a link: update this viewer, then let the view refresh."""
        done = {item.key for item in result.items
                if item.status in (link_service.LINKED, link_service.UNCHANGED)}
        changed = [document for document in documents if document.key in done]

        def apply():
            if self.closed:
                return False
            for document in changed:
                self.linked[document.key] = result.target
                self.selected.pop(document.key, None)
            return self.on_change(changed)

        self.publish(apply)
        if result.linked and callable(self.linking.on_linked):
            try:
                self.linking.on_linked(result)
            except Exception:
                pass  # The view's listing refresh never undoes a confirmed link.


class LinkForm:
    """Confirmation dialog: client, expediente, review, explicit confirmation."""

    def __init__(self, controller, documents, *, multiple):
        self.controller = controller
        self.page = controller.page
        self.linking = controller.linking
        self.documents = list(documents)
        self.requests = [self.linking.request(document) for document in self.documents]
        self.multiple = multiple
        self.closed = False
        self.plan = None
        self.result = None
        self.checks = ()
        self.client_id = None
        self.expedient_id = None
        self.client_ids = {}
        self.expedient_ids = {}
        # DV25-P3A filing preview: bound to one expediente, never persisted.
        self.filing = None
        self.folder = None
        self.choices = {}
        self.preview = ()
        self.folder_select = None
        self.nomenclature_selects = {}
        self._busy = threading.Lock()
        self.layout = link_layout(*_viewport(self.page))

        self.status = ft.Text("", size=13, color=Q_MUTED, selectable=True)
        self.document_column = ft.Column(spacing=6, tight=True)
        self.review_column = ft.Column(spacing=4, tight=True)
        self.transfer = ft.Checkbox(value=False, visible=False, on_change=self._on_transfer,
                                    label="Autorizo el traslado de documentos ya vinculados a otro "
                                          "expediente o cliente (confirmación especial).")
        self.confirm = ft.Checkbox(value=False, disabled=True, label="Confirmo la vinculación.",
                                   on_change=self._on_confirm)
        self.submit_button = primary_button("Vincular", self.submit)
        self.submit_button.disabled = True
        self.cancel_button = secondary_button("Cancelar", self.close)
        self.archive_button = secondary_button("Vincular y archivar copia", self.submit_and_archive)
        self.archive_button.disabled = True
        self.archive_button.tooltip = ARCHIVE_AFTER_LINK
        # The P3A preview table (``filing-preview``); the Box selectors live in ``_box_column``.
        self.filing_column = ft.Column(spacing=6, tight=True, data="filing")
        self._box_column = ft.Column(spacing=10, tight=True, data="filing-box")
        field = self.layout.pair or self.layout.field
        self.client_select = AppAutocomplete(
            self.page, "Cliente", options=[], width=field, max_results=10,
            on_select=self._on_client, allow_free_text=False)
        self.expedient_select = AppAutocomplete(
            self.page, "Expediente del cliente", options=[], width=field, max_results=10,
            on_select=self._on_expedient, allow_free_text=False)

        title = (f"Vincular {len(self.documents)} documentos seleccionados" if multiple
                 else "Vincular a expediente")
        selectable = self._inspect()
        if selectable:
            self._reset_filing()
            body = [self._zones([self._documents_card(), self._destination_card()], [self._box_card()]),
                    self._review_card(), self._preview_card()]
            height = self.layout.height
        else:
            self.cancel_button.content.value = "Cerrar"
            self.submit_button.visible = False
            body = [self._documents_card()]
            height = min(self.layout.height, 220 + 72 * len(self.documents))
        self.dialog = ft.AlertDialog(
            modal=True,
            # DV24 semantic title; the header inside the content shows it.
            title=ft.Text(title, visible=False),
            title_padding=ft.Padding.all(0),
            content=ft.Container(
                width=self.layout.width, height=height, data="link-shell",
                content=ft.Column(spacing=0, controls=[
                    self._header(title),
                    ft.Container(
                        expand=True, padding=ft.Padding.symmetric(horizontal=LinkLayout.PAD, vertical=16),
                        content=ft.Column(body, spacing=14, scroll=ft.ScrollMode.AUTO,
                                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                          data="link-body")),
                    self._status_bar(),
                ])),
            content_padding=ft.Padding.all(0),
            actions=[self.cancel_button, self.archive_button, self.submit_button],
            actions_alignment=ft.MainAxisAlignment.END,
            actions_padding=ft.Padding.only(left=LinkLayout.PAD, right=LinkLayout.PAD, top=10, bottom=14),
            inset_padding=ft.Padding.symmetric(horizontal=LinkLayout.INSET_H, vertical=LinkLayout.INSET_V),
            shape=ft.RoundedRectangleBorder(radius=14),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=Q_SURFACE,
            data=self,
        )

    # ------------------------------------------------------------------ composition (DV26-UI1)

    def _header(self, title):
        scope = f"Lote · {len(self.documents)} documentos" if self.multiple else "Documento activo"
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=LinkLayout.PAD, vertical=14),
            gradient=ft.LinearGradient(begin=ft.Alignment(-1, 0), end=ft.Alignment(1, 0),
                                       colors=[Q_NAVY, "#0B3B7A"]),
            data="link-header",
            content=ft.Row(spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Container(
                    width=40, height=40, bgcolor="#1D6FD8", border_radius=10, alignment=ft.Alignment(0, 0),
                    content=ft.Icon(ft.Icons.PLAYLIST_ADD_CHECK if self.multiple else ft.Icons.LINK,
                                    color=Q_WHITE, size=22)),
                ft.Column(expand=True, spacing=2, tight=True, controls=[
                    ft.Text(title, size=19, weight=ft.FontWeight.BOLD, color=Q_WHITE, data="link-title"),
                    ft.Text(LOGICAL_ONLY, size=11.5, color="#C7D2FE"),
                ]),
                _badge(scope, Q_WHITE, "#FFFFFF26"),
                ft.IconButton(
                    icon=ft.Icons.CLOSE, icon_color=Q_WHITE, tooltip="Cerrar", on_click=self.close,
                    style=ft.ButtonStyle(side=ft.BorderSide(1, "#FFFFFF66"),
                                         shape=ft.RoundedRectangleBorder(radius=8))),
            ]),
        )

    def _zones(self, left, right):
        """Two columns when the window allows it, otherwise stacked; never clipped."""
        layout = self.layout
        if not layout.wide:
            return ft.Column([*left, *right], spacing=14, tight=True,
                             horizontal_alignment=ft.CrossAxisAlignment.STRETCH, data="link-zones")
        return ft.Row(spacing=LinkLayout.GAP, vertical_alignment=ft.CrossAxisAlignment.START,
                      data="link-zones", controls=[
                          ft.Column(left, width=layout.left, spacing=14, tight=True,
                                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                          ft.Column(right, width=layout.right, spacing=14, tight=True,
                                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                      ])

    def _documents_card(self):
        title = (f"Documentos a vincular ({len(self.documents)})" if self.multiple
                 else "Documento a vincular")
        return _card(title, ft.Icons.DESCRIPTION_OUTLINED, [self.document_column], data="documents-card")

    def _destination_card(self):
        selects = [self.client_select.control, self.expedient_select.control]
        fields = (ft.Row(selects, spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)
                  if self.layout.pair else ft.Column(selects, spacing=10, tight=True))
        return _card("Destino: cliente y expediente", ft.Icons.FOLDER_SHARED_OUTLINED, [fields],
                     data="destination-card")

    def _box_card(self):
        return _card(BOX_TITLE, ft.Icons.CLOUD_OUTLINED, [
            ft.Text(filing_service.PREVIEW_ONLY, size=11.5, color=Q_TEXT, data="preview-only"),
            ft.Row([ft.Icon(ft.Icons.BLOCK, size=16, color=Q_NAVY),
                    ft.Text(BOX_NO_WRITES, size=11.5, weight=ft.FontWeight.W_600, color=Q_NAVY,
                            expand=True, data="box-no-writes")],
                   spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
            self._box_column,
        ], badge=_badge(BOX_BADGE, Q_NAVY, "#E0F2FE"), bgcolor=Q_BOX_BG, border=Q_BOX_BORDER,
            data="box-card")

    def _review_card(self):
        # Full width: the special transfer and confirmation labels are long.
        controls = [self.review_column, self.transfer, self.confirm]
        if self.multiple:
            controls.append(ft.Text(link_service.BATCH_POLICY, size=11, color=Q_MUTED))
        return _card("Revisión y confirmación", ft.Icons.FACT_CHECK_OUTLINED, controls, data="review-card")

    def _preview_card(self):
        return _card(PREVIEW_TITLE, ft.Icons.TABLE_CHART_OUTLINED, [self.filing_column], data="preview-card")

    def _status_bar(self):
        """Status and errors outside the scrolled body: always visible above the actions."""
        return ft.Container(
            padding=ft.Padding.only(left=LinkLayout.PAD, right=LinkLayout.PAD, top=10),
            border=ft.Border(top=ft.BorderSide(1, Q_BORDER)),
            data="link-status-bar",
            content=ft.Column(spacing=2, tight=True, controls=[
                self.status,
                ft.Text(ARCHIVE_AFTER_LINK, size=11, color=Q_MUTED, data="archive-after-link"),
            ]),
        )

    # ------------------------------------------------------------------ setup

    def _inspect(self):
        """Current link of every document; True when at least one can be linked."""
        try:
            self.checks = link_service.inspect_documents(
                self.linking.actor, self.requests, db_path=self.linking.db_path)
        except link_service.DocumentLinkError as exc:
            self._set_status(str(exc), Q_ERROR)
            return False
        except Exception:
            self._set_status("No se pudo consultar el estado de los documentos.", Q_ERROR)
            return False
        self.document_column.controls = [self._document_line(check) for check in self.checks]
        linkable = [check for check in self.checks if check.outcome == link_service.READY]
        if not linkable:
            unlinkable = all(check.outcome == link_service.NOT_LINKABLE for check in self.checks)
            self._set_status(link_service.NOT_LINKABLE_MESSAGE if unlinkable
                             else "Ningún documento se puede vincular.", Q_WARNING)
            return False
        try:
            options = link_service.client_options()
        except Exception:
            self._set_status("No se pudieron cargar los clientes.", Q_ERROR)
            return False
        self.client_ids = {option["label"]: int(option["id"]) for option in options}
        self.client_select.set_options(options)
        current = next((check.client_id for check in linkable if check.client_id), None)
        option = next((option for option in options if int(option["id"]) == current), None)
        if option is not None:
            # The current client is preselected; the expediente is always an explicit choice.
            self.client_select.set_value(option["label"], update=False)
            self.client_select.selected_option = option
            self._load_expedients(current)
        return True

    @staticmethod
    def _document_line(check):
        if check.outcome == link_service.READY:
            current = (f"Expediente actual: #{check.expedient_id}" if check.expedient_id
                       else "Sin expediente")
            if check.client_id:
                current += f" · Cliente #{check.client_id}"
            text, color = current, Q_MUTED
        else:
            text, color = check.message, OUTCOME_COLORS.get(check.outcome, Q_TEXT)
        reference = f"Bandeja #{check.inbox_item_id}" if check.inbox_item_id else "Carpeta de expediente"
        label = OUTCOME_LABELS.get(check.outcome)
        badge = ([_badge(label, Q_SUCCESS if check.outcome == link_service.READY else color, "#F1F5F9")]
                 if label else [])
        return ft.Container(
            data=check.key, padding=ft.Padding.symmetric(horizontal=10, vertical=8), border_radius=8,
            bgcolor=Q_SURFACE, border=ft.Border.all(1, Q_BORDER),
            content=ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=18, color=Q_PRIMARY),
                ft.Column(spacing=1, tight=True, expand=True, controls=[
                    ft.Text(check.name, size=13, weight=ft.FontWeight.W_600, color=Q_TEXT, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS, tooltip=check.path or None),
                    ft.Text(f"{reference} · {text}", size=11, color=color),
                ]),
                *badge,
            ]),
        )

    # ------------------------------------------------------------------ selection

    def _load_expedients(self, client_id):
        self.client_id = client_id
        self.expedient_id = None
        self._reset_filing()
        try:
            options = link_service.expedient_options(client_id)
        except Exception:
            options = []
            self._set_status("No se pudieron cargar los expedientes del cliente.", Q_ERROR)
        self.expedient_ids = {option["label"]: int(option["id"]) for option in options}
        self.expedient_select.set_options(options, clear_value=True)

    def _on_client(self, label):
        if self.closed or self.result is not None:
            return
        self._load_expedients(self.client_ids.get(label))
        self._review()

    def _on_expedient(self, label):
        if self.closed or self.result is not None:
            return
        self.expedient_id = self.expedient_ids.get(label)
        self._load_filing()
        self._review()

    # ------------------------------------------------------------------ filing preview (P3A)

    def _reset_filing(self):
        """Another client or expediente: folder, nomenclatures and preview are dropped."""
        self.filing = None
        self.folder = None
        self.choices = {}
        self.preview = ()
        self.folder_select = None
        self.nomenclature_selects = {}
        self._box_column.controls = [_hint(CHOOSE_EXPEDIENT)]
        self.filing_column.controls = [_hint(PREVIEW_PENDING, data="preview-empty")]

    def _load_filing(self):
        """Read-only context of the chosen expediente; it never blocks the logical link."""
        self._reset_filing()
        if not (self.client_id and self.expedient_id):
            return
        try:
            self.filing = filing_service.load_context(self.client_id, self.expedient_id,
                                                      db_path=self.linking.db_path)
        except filing_service.FilingPlanError as exc:
            self._box_column.controls = [_banner(str(exc), Q_WARNING)]
            return
        except Exception:
            self._box_column.controls = [_banner(filing_service.CATALOG_UNAVAILABLE, Q_WARNING)]
            return
        context = self.filing
        width = self.layout.box_field
        controls = [_banner(notice, Q_WARNING, data="filing-notice") for notice in context.notices]
        if context.root.available:
            self.folder_select = AppAutocomplete(
                self.page, "Carpeta existente (ruta relativa)", width=width, max_results=10,
                options=[{"id": folder.relative or ".", "label": folder.label}
                         for folder in context.folders],
                on_select=lambda label: self._on_folder(context, label), allow_free_text=False)
            controls.append(self.folder_select.control)
            for check in self.checks:
                if not context.options or filing_service.blocker(context, check):
                    continue
                select = AppAutocomplete(
                    self.page, f"Nomenclatura · {check.name}", width=width, max_results=10,
                    options=[{"id": option.key, "label": option.label, "subtitle": option.subtitle}
                             for option in context.options],
                    on_select=lambda label, key=check.key: self._on_nomenclature(context, key, label),
                    allow_free_text=False)
                self.nomenclature_selects[check.key] = select
            if self.nomenclature_selects:
                controls.append(ft.Text("Nomenclatura / rol por documento", size=12,
                                        weight=ft.FontWeight.W_600, color=Q_NAVY))
                controls += [select.control for select in self.nomenclature_selects.values()]
        self._box_column.controls = controls
        self._update_preview()

    def _on_folder(self, context, label):
        if self.closed or self.result is not None or context is not self.filing:
            return
        self.folder = next((folder.relative for folder in context.folders if folder.label == label), None)
        self._update_preview()
        self._refresh()

    def _on_nomenclature(self, context, key, label):
        if self.closed or self.result is not None or context is not self.filing:
            return
        option = next((option for option in context.options if option.label == label), None)
        if option is None:
            self.choices.pop(key, None)
        else:
            self.choices[key] = option.key
        self._update_preview()
        self._refresh()

    def _update_preview(self):
        """Proposed names for every document; projected only, nothing is reserved."""
        context = self.filing
        if context is None:
            return
        self.preview = filing_service.build_preview(context, self.checks, folder=self.folder,
                                                    choices=self.choices)
        table = ft.DataTable(
            column_spacing=18,
            heading_row_height=38,
            heading_row_color="#F1F5F9",
            border=ft.Border.all(1, Q_BORDER),
            border_radius=8,
            horizontal_lines=ft.BorderSide(1, "#EAECF0"),
            columns=[ft.DataColumn(ft.Text(name, size=11, weight=ft.FontWeight.W_600, color=Q_NAVY))
                     for name in PREVIEW_COLUMNS],
            rows=[ft.DataRow(cells=[
                *[self._cell(value) for value in (
                    row.source_name, f"#{row.inbox_item_id}" if row.inbox_item_id else "Sin Bandeja",
                    row.nomenclature, row.folder, row.proposed_name)],
                self._cell(row.message, PREVIEW_COLORS.get(row.status, Q_TEXT)),
            ]) for row in self.preview])
        # Horizontal scroll for long names; the placeholder is replaced.
        self.filing_column.controls = [ft.Row([table], scroll=ft.ScrollMode.AUTO, data="filing-preview")]

    @staticmethod
    def _cell(value, color=Q_TEXT):
        return ft.DataCell(ft.Text(str(value or "—"), size=11, color=color, selectable=True))

    def _review(self):
        """Pre-validate every document against the chosen expediente; no writes."""
        self.plan = None
        self.review_column.controls = []
        self.transfer.value = self.transfer.visible = False
        self._reset_confirmation()
        if self.client_id and self.expedient_id:
            try:
                self.plan = link_service.prepare_link(
                    self.linking.actor, self.requests, client_id=self.client_id,
                    expedient_id=self.expedient_id, db_path=self.linking.db_path)
            except link_service.DocumentLinkError as exc:
                self._set_status(str(exc), Q_ERROR)
                return
            except Exception:
                self._set_status("No se pudo revisar la vinculación.", Q_ERROR)
                return
            self.review_column.controls = [ft.Text("Revisión", size=12, weight=ft.FontWeight.W_700,
                                                   color=Q_NAVY)] + [
                self._outcome_line(check.name, check.outcome, check.message)
                for check in self.plan.checks]
            self.transfer.visible = bool(self.plan.with_outcome(link_service.TRANSFER))
            self._reset_confirmation()
            self._set_status("" if self.plan.actionable(True) else
                             "No hay documentos que vincular a este expediente.", Q_MUTED)
            return
        self._set_status("", Q_MUTED)

    @staticmethod
    def _outcome_line(name, outcome, message):
        return ft.Text(f"{name}: {message}", size=12, color=OUTCOME_COLORS.get(outcome, Q_TEXT),
                       data=outcome, selectable=True)

    def _actionable(self):
        return self.plan.actionable(bool(self.transfer.value)) if self.plan is not None else 0

    def _reset_confirmation(self):
        """Every change of client, expediente or transfer asks for a new confirmation."""
        count = self._actionable()
        self.confirm.value = False
        self.confirm.disabled = not count
        self.confirm.label = (
            f"Confirmo vincular {count} documento(s) al expediente {self.plan.target.label} del "
            f"cliente #{self.plan.target.client_id}." if count else "Confirmo la vinculación.")
        self._set_actions(False)

    def _archivable(self):
        """DV28-FIX2: a Box root for the chosen expediente and at least one Bandeja document."""
        return (self.filing is not None and self.filing.root.available
                and any(request["inbox_item_id"] for request in self.requests))

    def _set_actions(self, ready):
        """Both link actions need the link confirmation; the archive one also a Box destination."""
        self.submit_button.disabled = not ready
        self.archive_button.disabled = not (ready and self._archivable())

    def _on_transfer(self, e=None):
        if self.closed or self.result is not None or self._busy.locked():
            return
        self._reset_confirmation()
        self._refresh()

    def _on_confirm(self, e=None):
        if self.closed or self.result is not None or self._busy.locked():
            return
        self._set_actions(bool(self.confirm.value and self._actionable()))
        self._refresh()

    # ------------------------------------------------------------------ lifecycle

    def _refresh(self):
        if not self.closed and getattr(self, "dialog", None) is not None:
            _flush(self.page, self.dialog)

    def _set_status(self, text, color):
        self.status.value = text
        self.status.color = color
        self._refresh()

    def submit(self, e=None):
        if (self.closed or self.result is not None or self.plan is None
                or not self._busy.acquire(blocking=False)):
            return None
        try:
            if not (self.confirm.value and self._actionable()):
                self._set_status(link_service.NOT_CONFIRMED, Q_ERROR)
                return None
            self._set_actions(False)
            self._set_status("Vinculando…", Q_MUTED)
            try:
                result = link_service.execute_link(self.plan, confirmed=True,
                                                   allow_transfer=bool(self.transfer.value))
            except link_service.DocumentLinkError as exc:
                self._set_actions(True)
                self._set_status(str(exc), Q_ERROR)
                return None
            except Exception:
                self._set_actions(True)
                self._set_status(link_service.LINK_FAILED, Q_ERROR)
                return None
            self.result = result
            self.review_column.controls = [ft.Text("Resultado", size=12, weight=ft.FontWeight.W_700,
                                                   color=Q_NAVY)] + [
                self._outcome_line(item.name, item.status, item.message) for item in result.items]
            self.submit_button.visible = self.archive_button.visible = False
            self.confirm.disabled = self.transfer.disabled = True
            self.client_select.set_disabled(True, update=False)
            self.expedient_select.set_disabled(True, update=False)
            for select in [self.folder_select, *self.nomenclature_selects.values()]:
                if select is not None:
                    select.set_disabled(True, update=False)
            self.cancel_button.content.value = "Cerrar"
            color = Q_ERROR if result.problems and not result.linked else (
                Q_WARNING if result.problems else Q_SUCCESS)
            lines = [f"{result.summary}. Por {result.user['username']}."]
            if result.partial:
                lines.append("Resultado parcial: " + result.policy)
            self._set_status(" ".join(lines), color)
            self.controller.finished(self.documents, result)
            return result
        finally:
            self._busy.release()

    def submit_and_archive(self, e=None):
        """DV28-FIX2: the confirmed link, then the archive review of only the linked documents.

        Nothing is copied here: ArchiveForm opens with the folder and nomenclatures
        chosen in this form preselected and still asks for its own consent. When no
        document was linked the result stays in this form and nothing is archived.
        """
        if self.archive_button.disabled or not self._archivable():
            return None
        result = self.submit()
        if result is None:
            return None
        linked = {item.key for item in result.items
                  if item.status in (link_service.LINKED, link_service.UNCHANGED)}
        documents = [document for document in self.documents if document.key in linked]
        if not documents:
            return result
        missing = len(self.documents) - len(documents)
        folder, choices = self.folder, {key: value for key, value in self.choices.items() if key in linked}
        self.close()
        self.controller.open_archive_linked(
            documents, multiple=self.multiple, folder=folder, choices=choices,
            notice=NOT_LINKED_NOT_ARCHIVED.format(count=missing) if missing else "")
        return result

    def show(self):
        _present_dialog(self.page, self.dialog)
        return self

    def close(self, e=None):
        """Cancel (no writes) or close after the result."""
        if self.closed:
            return
        self.closed = True
        _request_dismiss(self.page, self.dialog)
        if _contains(self.page.overlay, self.dialog):
            self.page.overlay.remove(self.dialog)
            self.page.update()
        else:
            _flush(self.page, self.dialog)
