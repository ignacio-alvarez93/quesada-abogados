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
"""
import threading
from dataclasses import dataclass, replace

import flet as ft

from backend.services import document_viewer_filing_plan_service as filing_service
from backend.services import document_viewer_link_service as link_service
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.document_viewer_modal import (
    Q_MUTED, Q_NAVY, Q_PRIMARY, Q_TEXT, _command, _contains, _flush, _info_separator,
    _present_dialog, _request_dismiss,
)


Q_SUCCESS = "#027A48"
Q_ERROR = "#B42318"
Q_WARNING = "#B54708"

LOGICAL_ONLY = ("Vinculación lógica en el CRM: no copia a Box, no mueve, renombra ni modifica "
                "archivos y no importa documentos.")
NO_SELECTION = "Marca documentos en el comparador para vincularlos juntos."

OUTCOME_COLORS = {
    link_service.READY: Q_TEXT,
    link_service.LINKED: Q_SUCCESS,
    link_service.UNCHANGED: Q_MUTED,
    link_service.TRANSFER: Q_WARNING,
    link_service.NOT_LINKABLE: Q_WARNING,
    link_service.REJECTED: Q_ERROR,
    link_service.FAILED: Q_ERROR,
}


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
        return [button for button in (self.link_button, self.selected_button) if button is not None]

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
        return controls

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

    def _open(self, documents, multiple):
        # One form at a time: a second click while it is open does nothing.
        if self.closed or (self.form is not None and not self.form.closed):
            return None
        self.form = LinkForm(self, documents, multiple=multiple).show()
        return self.form

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

        self.status = ft.Text("", size=12, color=Q_MUTED, selectable=True)
        self.document_column = ft.Column(spacing=4, tight=True)
        self.review_column = ft.Column(spacing=4, tight=True)
        self.transfer = ft.Checkbox(value=False, visible=False, on_change=self._on_transfer,
                                    label="Autorizo el traslado de documentos ya vinculados a otro "
                                          "expediente o cliente (confirmación especial).")
        self.confirm = ft.Checkbox(value=False, disabled=True, label="Confirmo la vinculación.",
                                   on_change=self._on_confirm)
        self.submit_button = primary_button("Vincular", self.submit)
        self.submit_button.disabled = True
        self.cancel_button = secondary_button("Cancelar", self.close)
        self.archive_button = secondary_button("Vincular y archivar copia", None)
        self.archive_button.disabled = True
        self.archive_button.tooltip = filing_service.ARCHIVE_PENDING
        self.filing_column = ft.Column(spacing=6, tight=True, data="filing")
        self.client_select = AppAutocomplete(
            self.page, "Cliente", options=[], width=440, max_results=10,
            on_select=self._on_client, allow_free_text=False)
        self.expedient_select = AppAutocomplete(
            self.page, "Expediente del cliente", options=[], width=440, max_results=10,
            on_select=self._on_expedient, allow_free_text=False)

        title = (f"Vincular {len(self.documents)} documentos seleccionados" if multiple
                 else "Vincular a expediente")
        body = [ft.Text(LOGICAL_ONLY, size=11, color=Q_MUTED), self.document_column]
        selectable = self._inspect()
        if selectable:
            self._reset_filing()
            body += [self.client_select.control, self.expedient_select.control,
                     self.review_column, self.transfer, self.confirm]
            if multiple:
                body.append(ft.Text(link_service.BATCH_POLICY, size=11, color=Q_MUTED))
            body.append(self.filing_column)
        else:
            self.cancel_button.content.value = "Cerrar"
            self.submit_button.visible = False
        body += [self.status, ft.Text(f"Vincular y archivar copia: {filing_service.ARCHIVE_PENDING}.",
                                      size=11, color=Q_MUTED, data="archive-pending")]
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Container(width=760, content=ft.Column(body, tight=True, spacing=8,
                                                               scroll=ft.ScrollMode.AUTO)),
            actions=[self.cancel_button, self.archive_button, self.submit_button],
            actions_alignment=ft.MainAxisAlignment.END,
            data=self,
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
        return ft.Column(spacing=0, tight=True, data=check.key, controls=[
            ft.Text(check.name, size=13, weight=ft.FontWeight.W_600, color=Q_TEXT, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=check.path or None),
            ft.Text(f"{reference} · {text}", size=11, color=color),
        ])

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
        self.filing_column.controls = [
            ft.Text("Archivo en Box (previsualización)", size=12, weight=ft.FontWeight.W_700,
                    color=Q_NAVY),
            ft.Text(filing_service.PREVIEW_ONLY, size=11, color=Q_MUTED, data="preview-only"),
            ft.Text("Elige un expediente para ver sus carpetas y nomenclaturas.", size=11,
                    color=Q_MUTED),
        ]

    def _load_filing(self):
        """Read-only context of the chosen expediente; it never blocks the logical link."""
        self._reset_filing()
        if not (self.client_id and self.expedient_id):
            return
        try:
            self.filing = filing_service.load_context(self.client_id, self.expedient_id,
                                                      db_path=self.linking.db_path)
        except filing_service.FilingPlanError as exc:
            self.filing_column.controls[-1] = ft.Text(str(exc), size=11, color=Q_WARNING)
            return
        except Exception:
            self.filing_column.controls[-1] = ft.Text(filing_service.CATALOG_UNAVAILABLE, size=11,
                                                      color=Q_WARNING)
            return
        context = self.filing
        controls = self.filing_column.controls[:2] + [
            ft.Text(notice, size=11, color=Q_WARNING, data="filing-notice") for notice in context.notices]
        if context.root.available:
            self.folder_select = AppAutocomplete(
                self.page, "Carpeta existente (ruta relativa)", width=440, max_results=10,
                options=[{"id": folder.relative or ".", "label": folder.label}
                         for folder in context.folders],
                on_select=lambda label: self._on_folder(context, label), allow_free_text=False)
            controls.append(self.folder_select.control)
            for check in self.checks:
                if not context.options or filing_service.blocker(context, check):
                    continue
                select = AppAutocomplete(
                    self.page, f"Nomenclatura · {check.name}", width=440, max_results=10,
                    options=[{"id": option.key, "label": option.label, "subtitle": option.subtitle}
                             for option in context.options],
                    on_select=lambda label, key=check.key: self._on_nomenclature(context, key, label),
                    allow_free_text=False)
                self.nomenclature_selects[check.key] = select
                controls.append(select.control)
        self.filing_column.controls = controls
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
            column_spacing=12,
            columns=[ft.DataColumn(ft.Text(name, size=11, weight=ft.FontWeight.W_600)) for name in (
                "Origen", "Bandeja", "Nomenclatura / rol", "Subcarpeta", "Nombre propuesto", "Estado")],
            rows=[ft.DataRow(cells=[self._cell(value) for value in (
                row.source_name, f"#{row.inbox_item_id}" if row.inbox_item_id else "Sin Bandeja",
                row.nomenclature, row.folder, row.proposed_name, row.message)])
                for row in self.preview])
        controls = [c for c in self.filing_column.controls if c.data != "filing-preview"]
        self.filing_column.controls = controls + [
            ft.Row([table], scroll=ft.ScrollMode.AUTO, data="filing-preview")]

    @staticmethod
    def _cell(value):
        return ft.DataCell(ft.Text(str(value or "—"), size=11, selectable=True))

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
        self.submit_button.disabled = True

    def _on_transfer(self, e=None):
        if self.closed or self.result is not None or self._busy.locked():
            return
        self._reset_confirmation()
        self._refresh()

    def _on_confirm(self, e=None):
        if self.closed or self.result is not None or self._busy.locked():
            return
        self.submit_button.disabled = not (self.confirm.value and self._actionable())
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
            self.submit_button.disabled = True
            self._set_status("Vinculando…", Q_MUTED)
            try:
                result = link_service.execute_link(self.plan, confirmed=True,
                                                   allow_transfer=bool(self.transfer.value))
            except link_service.DocumentLinkError as exc:
                self.submit_button.disabled = False
                self._set_status(str(exc), Q_ERROR)
                return None
            except Exception:
                self.submit_button.disabled = False
                self._set_status(link_service.LINK_FAILED, Q_ERROR)
                return None
            self.result = result
            self.review_column.controls = [ft.Text("Resultado", size=12, weight=ft.FontWeight.W_700,
                                                   color=Q_NAVY)] + [
                self._outcome_line(item.name, item.status, item.message) for item in result.items]
            self.submit_button.visible = False
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
