"""DV25-P3B2: "Archivar copia en Box" from the document viewer.

Reusable confirmation dialog over document_viewer_box_archive_service, the
only gate of the viewer's archive: this module never touches the filesystem,
the database or Box, and it does not know how the copy is made.

Flow: the documents (active one, or the comparator selection snapshotted when
the dialog opens) are inspected read-only; the destination is the client and
expediente they are ALREADY linked to, shown explicitly. The user picks an
existing folder of that expediente's Box root and a catalog nomenclature per
document; every change asks the service for a new read-only review (projected
names, collisions, fingerprint) and drops the consent. ``Archivar copia en
Box`` stays disabled until there is a complete review and its own checkbox
(never the ``Vincular`` one) is ticked; the service revalidates everything
right before each copy. Cancel/close write nothing. The result is shown per
document with the effective name the backend returned; a partial result is
never reported as a success, and a finished dialog never runs again.

DV28-FIX2: after ``Vincular y archivar copia`` the dialog may open with the
folder and nomenclatures chosen in LinkForm. Only those still valid for this
review are kept and shown selected; the consent is asked for as always.
"""
import threading

import flet as ft

from backend.services import document_viewer_box_archive_service as archive_service
from frontend.components.app_autocomplete import AppAutocomplete
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.document_viewer_modal import (
    Q_MUTED, Q_NAVY, Q_TEXT, _contains, _flush, _present_dialog, _request_dismiss,
)


Q_SUCCESS = "#027A48"
Q_ERROR = "#B42318"
Q_WARNING = "#B54708"

SUBMIT_LABEL = "Archivar copia en Box"
CONSENT_IDLE = "Confirmo el archivado de la copia."

OUTCOME_COLORS = {
    archive_service.READY: Q_TEXT,
    archive_service.PENDING: Q_MUTED,
    archive_service.NOT_ARCHIVABLE: Q_WARNING,
    archive_service.REJECTED: Q_ERROR,
    archive_service.ARCHIVED: Q_SUCCESS,
    archive_service.FAILED: Q_ERROR,
    archive_service.INCOMPLETE: Q_ERROR,
    archive_service.NOT_ATTEMPTED: Q_WARNING,
}


class ArchiveForm:
    """Review, explicit consent and single execution of one archive."""

    def __init__(self, controller, documents, *, multiple, folder=None, choices=None, notice=""):
        self.controller = controller
        self.page = controller.page
        self.linking = controller.linking
        self.documents = list(documents)
        self.requests = [self.linking.request(document) for document in self.documents]
        self.multiple = multiple
        self.closed = False
        self.inspection = None
        self.target = None
        # Context the selectors were built from; late events of another context are ignored.
        self.context = None
        self.plan = None
        self.result = None
        # Fingerprint of the plan the user consented to; any new review drops it.
        self.consented = None
        # DV28-FIX2: choices carried from LinkForm; _keep_valid drops what does not apply here.
        self.folder = folder if isinstance(folder, str) else None
        self.choices = dict(choices or {})
        self.folder_select = None
        self.nomenclature_selects = {}
        self._busy = threading.Lock()

        self.status = ft.Text("", size=12, color=Q_MUTED, selectable=True)
        self.document_column = ft.Column(spacing=4, tight=True)
        self.selector_column = ft.Column(spacing=6, tight=True, data="archive-selectors")
        self.review_column = ft.Column(spacing=4, tight=True, data="archive-review")
        self.confirm = ft.Checkbox(value=False, disabled=True, label=CONSENT_IDLE,
                                   on_change=self._on_confirm)
        self.submit_button = primary_button(SUBMIT_LABEL, self.submit)
        self.submit_button.disabled = True
        self.cancel_button = secondary_button("Cancelar", self.close)
        self.blocker = archive_service.execution_blocker()

        title = (f"Archivar copia en Box · {len(self.documents)} documentos" if multiple
                 else "Archivar copia en Box")
        body = [ft.Text(archive_service.COPY_ONLY, size=11, color=Q_MUTED, data="copy-only"),
                self.document_column]
        if notice:
            body.insert(1, ft.Text(notice, size=11, color=Q_WARNING, data="archive-link-notice"))
        if self._inspect():
            body += [ft.Text(f"Destino: expediente {self.target.label} del cliente #{self.target.client_id} "
                             "(su vinculación actual).", size=12, weight=ft.FontWeight.W_600,
                             color=Q_NAVY, data="archive-target"),
                     self.selector_column, self.review_column, self.confirm]
            if multiple:
                body.append(ft.Text(archive_service.BATCH_POLICY, size=11, color=Q_MUTED))
        else:
            self.cancel_button.content.value = "Cerrar"
            self.submit_button.visible = False
        if self.blocker:
            self.submit_button.tooltip = self.blocker
            body.append(ft.Text(self.blocker, size=11, color=Q_WARNING, data="archive-blocked"))
        body.append(self.status)
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Container(width=760, content=ft.Column(body, tight=True, spacing=8,
                                                               scroll=ft.ScrollMode.AUTO)),
            actions=[self.cancel_button, self.submit_button],
            actions_alignment=ft.MainAxisAlignment.END,
            data=self,
        )

    # ------------------------------------------------------------------ setup

    def _inspect(self):
        """Eligibility of every document; True when there is something to review."""
        try:
            self.inspection = archive_service.inspect_archive(
                self.linking.actor, self.requests, db_path=self.linking.db_path)
        except archive_service.ArchiveError as exc:
            self._set_status(str(exc), Q_ERROR)
            return False
        except Exception:
            self._set_status("No se pudo consultar el estado de los documentos.", Q_ERROR)
            return False
        self.document_column.controls = [self._document_line(item) for item in self.inspection.items]
        self.target = self.inspection.target
        if self.target is None:
            self._set_status(self.inspection.message, Q_WARNING)
            return False
        self._prepare()
        if self.plan is not None and self._keep_valid(self.plan):
            self._prepare()
        if self.plan is None:
            return False
        self.context = self.plan.context
        self._build_selectors(self.context)
        return True

    def _keep_valid(self, plan):
        """Drop carried choices that are not an option of this review; True when one was dropped."""
        context = plan.context
        folder = self.folder if self.folder in {item.relative for item in context.folders} else None
        keys = {item.key for item in plan.items if item.outcome in (archive_service.READY, archive_service.PENDING)}
        options = {option.key for option in context.options}
        choices = {key: value for key, value in self.choices.items() if key in keys and value in options}
        changed = (folder, choices) != (self.folder, self.choices)
        self.folder, self.choices = folder, choices
        return changed

    @staticmethod
    def _document_line(item):
        reference = f"Bandeja #{item.inbox_item_id}" if item.inbox_item_id else "Carpeta de expediente"
        if item.outcome == archive_service.READY:
            text, color = f"Vinculado al expediente #{item.expedient_id} · Cliente #{item.client_id}", Q_MUTED
        else:
            text, color = item.message, OUTCOME_COLORS.get(item.outcome, Q_TEXT)
        return ft.Column(spacing=0, tight=True, data=item.key, controls=[
            ft.Text(item.name, size=13, weight=ft.FontWeight.W_600, color=Q_TEXT, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=item.path or None),
            ft.Text(f"{reference} · {text}", size=11, color=color),
        ])

    def _build_selectors(self, context):
        """Existing folders and catalog nomenclatures of the destination; never free text."""
        controls = [ft.Text(notice, size=11, color=Q_WARNING, data="archive-notice")
                    for notice in context.notices]
        if context.root.available:
            self.folder_select = AppAutocomplete(
                self.page, "Carpeta existente (ruta relativa)", width=440, max_results=10,
                options=[{"id": folder.relative or ".", "label": folder.label} for folder in context.folders],
                on_select=lambda label: self._on_folder(context, label), allow_free_text=False)
            if self.folder is not None:
                self.folder_select.set_value(next((folder.label for folder in context.folders
                                                   if folder.relative == self.folder), ""), update=False)
            controls.append(self.folder_select.control)
            for item in self.plan.items:
                if item.outcome not in (archive_service.READY, archive_service.PENDING) or not context.options:
                    continue
                select = AppAutocomplete(
                    self.page, f"Nomenclatura · {item.name}", width=440, max_results=10,
                    options=[{"id": option.key, "label": option.label, "subtitle": option.subtitle}
                             for option in context.options],
                    on_select=lambda label, key=item.key: self._on_nomenclature(context, key, label),
                    allow_free_text=False)
                if item.key in self.choices:
                    select.set_value(next((option.label for option in context.options
                                           if option.key == self.choices[item.key]), ""), update=False)
                self.nomenclature_selects[item.key] = select
                controls.append(select.control)
        self.selector_column.controls = controls

    # ------------------------------------------------------------------ review

    def _editable(self):
        return not (self.closed or self.result is not None or self._busy.locked())

    def _on_folder(self, context, label):
        if not self._editable() or context is not self.context:
            return
        self.folder = next((folder.relative for folder in context.folders if folder.label == label), None)
        self._prepare()
        self._refresh()

    def _on_nomenclature(self, context, key, label):
        if not self._editable() or context is not self.context:
            return
        option = next((option for option in context.options if option.label == label), None)
        if option is None:
            self.choices.pop(key, None)
        else:
            self.choices[key] = option.key
        self._prepare()
        self._refresh()

    def _prepare(self):
        """New read-only review for the current choices; the consent is always dropped."""
        try:
            plan = archive_service.prepare_archive(
                self.linking.actor, self.requests, client_id=self.target.client_id,
                expedient_id=self.target.expedient_id, folder=self.folder, choices=dict(self.choices),
                db_path=self.linking.db_path)
        except archive_service.ArchiveError as exc:
            self.plan = None
            self._reset_confirmation()
            self._set_status(str(exc), Q_ERROR)
            return
        except Exception:
            self.plan = None
            self._reset_confirmation()
            self._set_status("No se pudo revisar el archivado.", Q_ERROR)
            return
        self.plan = plan
        self._show_review()
        self._reset_confirmation()
        self._set_status("" if plan.ready else archive_service.NOTHING_READY, Q_MUTED)

    def _show_review(self):
        """Source -> destination per document; projected only, nothing is reserved."""
        plan = self.plan
        folder = plan.folder_label or "—"
        table = ft.DataTable(
            column_spacing=12,
            columns=[ft.DataColumn(ft.Text(name, size=11, weight=ft.FontWeight.W_600)) for name in (
                "Origen", "Bandeja", "Nomenclatura / rol", "Subcarpeta", "Nombre final", "Estado")],
            rows=[ft.DataRow(cells=[self._cell(value) for value in (
                item.name, f"#{item.inbox_item_id}" if item.inbox_item_id else "Sin Bandeja",
                item.nomenclature_label, folder if item.outcome == archive_service.READY else "",
                item.proposed_name, item.message)])
                for item in plan.items])
        self.review_column.controls = [
            ft.Text(f"Revisión · {len(plan.ready)} de {len(plan.items)} documento(s) listos", size=12,
                    weight=ft.FontWeight.W_700, color=Q_NAVY),
            ft.Row([table], scroll=ft.ScrollMode.AUTO, data="archive-preview"),
        ]

    @staticmethod
    def _cell(value):
        return ft.DataCell(ft.Text(str(value or "—"), size=11, selectable=True))

    def _reset_confirmation(self):
        """Every new review asks for a new, specific confirmation."""
        count = len(self.plan.ready) if self.plan is not None else 0
        self.consented = None
        self.confirm.value = False
        self.confirm.disabled = not count or bool(self.blocker)
        self.confirm.label = (
            f"Confirmo archivar una COPIA de {count} documento(s) en «{self.plan.folder_label}» del "
            f"expediente {self.plan.target.label} (cliente #{self.plan.target.client_id}), sin mover ni "
            "sobrescribir nada." if count else CONSENT_IDLE)
        self.submit_button.disabled = True

    def _on_confirm(self, e=None):
        if not self._editable():
            return
        ready = (self.confirm.value is True and self.plan is not None and bool(self.plan.ready)
                 and not self.blocker)
        self.consented = self.plan.fingerprint if ready else None
        self.submit_button.disabled = not ready
        self._refresh()

    # ------------------------------------------------------------------ lifecycle

    def _refresh(self):
        if not self.closed and getattr(self, "dialog", None) is not None:
            _flush(self.page, self.dialog)

    def _set_status(self, text, color):
        self.status.value = text
        self.status.color = color
        self._refresh()

    def _outcome_line(self, outcome):
        text = f"{outcome.name}: {outcome.message}"
        if outcome.destination:
            text += f" Destino: {outcome.destination}."
        if outcome.written_path:
            text += f" Archivo a revisar: {outcome.written_path}."
        return ft.Text(text, size=12, color=OUTCOME_COLORS.get(outcome.status, Q_TEXT),
                       data=outcome.status, selectable=True)

    def _lock_inputs(self):
        self.submit_button.visible = False
        self.confirm.disabled = True
        for select in [self.folder_select, *self.nomenclature_selects.values()]:
            if select is not None:
                select.set_disabled(True, update=False)
        self.cancel_button.content.value = "Cerrar"

    def submit(self, e=None):
        if (self.closed or self.result is not None or self.plan is None
                or not self._busy.acquire(blocking=False)):
            return None
        try:
            if not (self.confirm.value is True and self.consented and self.plan.ready):
                self._set_status(archive_service.NOT_CONFIRMED, Q_ERROR)
                return None
            if self.consented != self.plan.fingerprint:
                self._reset_confirmation()
                self._set_status(archive_service.STALE_CONSENT, Q_ERROR)
                return None
            self.submit_button.disabled = True
            self._set_status("Archivando…", Q_MUTED)
            try:
                result = archive_service.execute_archive(self.plan, confirmed=True,
                                                         fingerprint=self.consented)
            except Exception as exc:
                # Nothing was copied: review again from the current state and ask again.
                message = (str(exc) if isinstance(exc, archive_service.ArchiveError)
                           else archive_service.COPY_FAILED)
                self._prepare()
                self._set_status(message, Q_ERROR)
                return None
            self.result = result
            self.review_column.controls = [ft.Text("Resultado", size=12, weight=ft.FontWeight.W_700,
                                                   color=Q_NAVY)] + [
                self._outcome_line(outcome) for outcome in result.items]
            self._lock_inputs()
            color = Q_SUCCESS if result.complete else (Q_WARNING if result.archived else Q_ERROR)
            lines = [f"{result.summary}. Por {result.user['username']}."]
            if result.partial:
                lines.append("Resultado parcial: " + result.policy)
            elif not result.complete:
                lines.append("No se ha archivado ningún documento.")
            self._set_status(" ".join(lines), color)
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
