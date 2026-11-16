"""DV30-03: "Nueva tarea" / "Nuevo aviso" from the document viewer.

The task is a canonical TASK and the notice a Calendar alert, both created
through document_viewer_actions_service (calendar application services);
there is no viewer task list or outbox, and no SQL here. Nothing is created
by opening the viewer, changing document or page, or saving a note: only by
``Guardar`` in a form.

ActionsController lives as long as the viewer: the two commands of the
active document in the viewer header, enabled once the service has verified
the actor, the document and its expediente (read-only, off the UI thread,
cached per document). A Bandeja item without an expediente keeps them
disabled with "Vincula primero el documento a un expediente". ActionForm is
the short form presented above the viewer; closing it never touches the
viewer's document, page, zoom, queue or notes draft.
"""
import threading
import uuid
from dataclasses import dataclass, replace

import flet as ft

from backend.services import document_viewer_actions_service as actions_service
from frontend.components.document_viewer_modal import (
    Q_BORDER, Q_MUTED, Q_NAVY, Q_TEXT, Q_WHITE, _command, _contains, _flush, _present_dialog,
    _request_dismiss,
)
from frontend.components.document_viewer_notes_panel import target_key


TASK = "task"
ALERT = "alert"

IDLE = "idle"
CHECKING = "checking"
READY = "ready"
BLOCKED = "blocked"

TASK_LABEL = "Nueva tarea"
ALERT_LABEL = "Nuevo aviso"
CHECKING_HINT = "Verificando el documento y su expediente…"
NO_DOCUMENT = actions_service.NO_IDENTITY
CHECK_FAILED = "No se pudo verificar el documento."
SAVE_FAILED = "No se pudo guardar: no se ha creado nada."
FORM_WIDTH = 520

Q_SUCCESS = "#027A48"
Q_ERROR = "#B42318"

PRIORITY_LABELS = {"BAJA": "Baja", "NORMAL": "Normal", "ALTA": "Alta", "URGENTE": "Urgente"}


@dataclass(frozen=True)
class ViewerActions:
    """Task/notice context a view injects into the viewer.

    ``actor`` is the authenticated session user ({"id", "username"}); the
    service verifies it. Bandeja views add the (path, item id) pairs of their
    queue; expedient viewers rely on the viewer's expediente_id. ``run``
    executes background work (default: a daemon thread); ``on_created(result)``
    lets the view refresh; ``db_path`` is only for isolated tests.
    """
    actor: object = None
    inbox_items: tuple = ()
    on_created: object = None
    db_path: object = None
    run: object = None

    def with_inbox_items(self, pairs):
        known = []
        for path, item_id in pairs or ():
            path = str(path or "").strip()
            try:
                item_id = int(item_id or 0)
            except (TypeError, ValueError):
                item_id = 0
            if path and item_id > 0:
                known.append((path, item_id))
        return replace(self, inbox_items=tuple(known))

    def target(self, document, expediente_id=None):
        """Identity request for the service; None when none is trustworthy."""
        path = str(getattr(document, "path", "") or "").strip()
        if not path:
            return None
        item_id = (getattr(document, "source", None) or {}).get("inbox_item_id") \
            or dict(self.inbox_items).get(path)
        if item_id:
            return {"inbox_item_id": item_id, "path": path}
        if expediente_id is not None:
            return {"expediente_id": expediente_id, "path": path}
        return None


class DocumentActionsState:
    """Verification of one document: its context or why actions are blocked."""

    def __init__(self):
        self.status = IDLE
        self.token = 0
        self.context = None
        self.error = ""


class ActionsController:
    """Header commands of the viewer's active document.

    ``publish(apply)`` is the viewer's: under its publication lock, while the
    viewer is live, it runs ``apply`` and flushes when it returns True.
    """

    def __init__(self, actions, *, page, expediente_id, publish):
        self.actions = actions
        self.page = page
        self.expediente_id = expediente_id
        self.publish = publish
        self.closed = False
        self.states = {}
        self.document = None
        self.target = None
        self.key = None
        self.form = None
        # Controls of the current header, for the viewer and tests.
        self.row = None
        self.height = 36
        self.task_button = None
        self.alert_button = None

    @property
    def buttons(self):
        return [button for button in (self.task_button, self.alert_button) if button is not None]

    @property
    def state(self):
        return self.states.get(self.key)

    # ------------------------------------------------------------------ viewer API

    def header_controls(self, document, *, height=36):
        """Both commands for ``document``; the viewer holds its publication lock."""
        self.document = document
        self.target = self.actions.target(document, self.expediente_id)
        self.key = target_key(self.target) or f"unidentified:{getattr(document, 'key', '')}"
        state = self.states.setdefault(self.key, DocumentActionsState())
        if self.target is None:
            state.status, state.error = BLOCKED, NO_DOCUMENT
        self.height = height
        self.row = ft.Row(spacing=8, tight=True, data="viewer-actions")
        self._apply_state()
        self._ensure_checked()
        return [self.row]

    def refresh(self, documents):
        """Documents linked from the viewer: verify them again when shown."""
        for document in documents:
            state = self.states.get(target_key(self.actions.target(document, self.expediente_id)))
            if state is not None:
                state.status = IDLE
                state.token += 1  # a check already in flight predates the link
        if not self.closed and self.document is not None:
            self._ensure_checked()
            return self._apply_state()
        return False

    def close(self):
        """Viewer closed: an open form is closed and late results are dropped."""
        self.closed = True
        if self.form is not None:
            self.form.close()

    # ------------------------------------------------------------------ verification

    def _run(self, work):
        run = self.actions.run
        if callable(run):
            run(work)
        else:
            threading.Thread(target=work, daemon=True).start()

    def _ensure_checked(self):
        state = self.state
        if self.target is None or state is None or state.status != IDLE:
            return
        key, target = self.key, self.target
        state.status, state.error = CHECKING, ""
        state.token += 1
        token = state.token
        self._apply_state()

        def work():
            try:
                context, error = actions_service.resolve_context(
                    self.actions.actor, target, db_path=self.actions.db_path), ""
            except actions_service.DocumentActionError as exc:
                context, error = None, str(exc)
            except Exception:
                context, error = None, CHECK_FAILED

            def apply():
                if self.closed or state.token != token:
                    return False
                state.context, state.error = context, error
                state.status = READY if context is not None else BLOCKED
                return key == self.key and self._apply_state()

            self.publish(apply)

        self._run(work)

    def _apply_state(self):
        """Commands of the active document, in place: enabled only once verified."""
        state = self.state
        if state is None or self.row is None:
            return False
        ready = state.status == READY
        if ready:
            scope = f" Expediente {state.context.expediente_label}."
            task_hint = "Crear una tarea en el Calendario para este documento." + scope
            alert_hint = "Crear un aviso en el Calendario para este documento." + scope
        else:
            task_hint = alert_hint = (CHECKING_HINT if state.status in (IDLE, CHECKING)
                                      else state.error or CHECK_FAILED)
        self.task_button = _command(TASK_LABEL, lambda e: self.open(TASK), icon=ft.Icons.ADD_TASK,
                                    height=self.height, disabled=not ready, tooltip=task_hint)
        self.alert_button = _command(ALERT_LABEL, lambda e: self.open(ALERT),
                                     icon=ft.Icons.NOTIFICATIONS_ACTIVE_OUTLINED, height=self.height,
                                     disabled=not ready, tooltip=alert_hint)
        self.task_button.data, self.alert_button.data = TASK, ALERT
        self.row.controls = [self.task_button, self.alert_button]
        return True

    # ------------------------------------------------------------------ forms

    def open(self, kind):
        """Form for the active document; one at a time, never for a stale document."""
        state = self.state
        if (self.closed or state is None or state.status != READY
                or (self.form is not None and not self.form.closed)):
            return None
        self.form = ActionForm(self, kind, self.target, state.context).show()
        return self.form

    def created(self, result):
        if callable(self.actions.on_created):
            try:
                self.actions.on_created(result)
            except Exception:
                pass  # The view's refresh never undoes a created record.


class ActionForm:
    """Short task or notice form; created only by an explicit ``Guardar``.

    The document and expediente come from the verified context and are shown
    read-only. ``request_id`` is the idempotency key of this submission: a
    retry of the same data reuses it, edited data or a new form gets another.
    """

    def __init__(self, controller, kind, target, context):
        self.controller = controller
        self.page = controller.page
        self.actions = controller.actions
        self.kind = kind
        self.target = dict(target)
        self.context = context
        self.closed = False
        self.sending = False
        self.result = None
        self.request_id = None
        self.attempted = None
        self._lock = threading.Lock()

        self.title_field = ft.TextField(label="Título", max_length=actions_service.MAX_TITLE,
                                        text_size=13, autofocus=True)
        self.description_field = ft.TextField(
            label="Descripción", multiline=True, min_lines=2, max_lines=4,
            max_length=actions_service.MAX_DESCRIPTION, text_size=13)
        self.date_field = ft.TextField(label="Vencimiento (dd/mm/aaaa)" if kind == TASK
                                       else "Fecha del evento (dd/mm/aaaa)", width=230, text_size=13)
        self.time_field = ft.TextField(label="Hora (hh:mm)", width=140, text_size=13)
        self.warning_date_field = self.warning_time_field = self.responsible_field = None
        self.priority_field = ft.Dropdown(
            label="Prioridad", value="NORMAL", width=180, dense=True,
            options=[ft.dropdown.Option(key=key, text=PRIORITY_LABELS[key])
                     for key in actions_service.PRIORITIES])
        fields = [self.title_field, self.description_field,
                  ft.Row([self.date_field, self.time_field], spacing=10)]
        if kind == TASK:
            self.responsible_field = ft.TextField(label="Responsable (opcional)", text_size=13,
                                                  max_length=actions_service.MAX_RESPONSIBLE)
            fields += [self.priority_field, self.responsible_field]
        else:
            self.warning_date_field = ft.TextField(label="Inicio del aviso (dd/mm/aaaa)", width=230,
                                                   text_size=13)
            self.warning_time_field = ft.TextField(label="Hora (hh:mm)", width=140, text_size=13)
            fields += [ft.Row([self.warning_date_field, self.warning_time_field], spacing=10),
                       ft.Text("Sin inicio, el aviso se programa a la hora del evento.", size=11,
                               color=Q_MUTED),
                       self.priority_field]

        self.status = ft.Text("", size=12, color=Q_MUTED, selectable=True, data="action-status")
        self.cancel_button = _command("Cancelar", self.close, height=38)
        self.save_button = _command("Guardar", self.submit, icon=ft.Icons.SAVE_OUTLINED, primary=True,
                                    height=38)
        title = TASK_LABEL if kind == TASK else ALERT_LABEL
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=Q_NAVY),
            content=ft.Container(
                width=FORM_WIDTH, data="action-form",
                content=ft.Column(tight=True, spacing=10, scroll=ft.ScrollMode.AUTO, controls=[
                    self._context_card(), *fields, self.status]),
            ),
            actions=[self.cancel_button, self.save_button],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=14),
            bgcolor=Q_WHITE,
            data=self,
        )

    def _context_card(self):
        """Document and expediente of the verified context: shown, never editable."""
        context = self.context
        return ft.Container(
            padding=10, border_radius=8, bgcolor="#F8FAFC", border=ft.Border.all(1, Q_BORDER),
            data="action-context",
            content=ft.Column(spacing=2, tight=True, controls=[
                ft.Text(f"Documento: {context.document_name}", size=13, weight=ft.FontWeight.W_600,
                        color=Q_TEXT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{context.document_label} · Expediente {context.expediente_label}", size=12,
                        color=Q_MUTED),
                ft.Text("Se creará en el Calendario"
                        + (" (Tareas)." if self.kind == TASK else " (Avisos)."), size=11, color=Q_MUTED),
            ]),
        )

    # ------------------------------------------------------------------ values

    @staticmethod
    def _moment(date_field, time_field):
        date, time = str(date_field.value or "").strip(), str(time_field.value or "").strip()
        if not date and not time:
            return ""
        return f"{date} {time}".strip()

    def payload(self):
        """Form values; the service validates every one of them."""
        values = {
            "titulo": str(self.title_field.value or ""),
            "descripcion": str(self.description_field.value or ""),
            "prioridad": str(self.priority_field.value or "NORMAL"),
        }
        moment = self._moment(self.date_field, self.time_field)
        if self.kind == TASK:
            values.update(fecha_vencimiento=moment,
                          responsable=str(self.responsible_field.value or ""))
        else:
            values.update(fecha_evento=moment,
                          fecha_inicio_aviso=self._moment(self.warning_date_field,
                                                          self.warning_time_field))
        return values

    def _set_inputs(self, disabled):
        for field in (self.title_field, self.description_field, self.date_field, self.time_field,
                      self.warning_date_field, self.warning_time_field, self.priority_field,
                      self.responsible_field):
            if field is not None:
                field.disabled = disabled

    def _set_save(self, label, disabled):
        # The handler stays: ``sending`` turns a click during a save into a no-op.
        self.save_button.disabled = disabled
        self.save_button.content.controls[-1].value = label

    def _set_status(self, text, color):
        self.status.value = text
        self.status.color = color

    def _refresh(self):
        if not self.closed and not self.controller.closed:
            _flush(self.page, self.dialog)

    # ------------------------------------------------------------------ submission

    def submit(self, e=None):
        """Human confirmation: one service call per click, never two at once."""
        with self._lock:
            if self.closed or self.controller.closed or self.sending or self.result is not None:
                return False
            values = self.payload()
            if values != self.attempted or self.request_id is None:
                # New data is a new submission; the same data retries the same one.
                self.request_id, self.attempted = uuid.uuid4().hex, values
            self.sending = True
        request_id, target, expected = self.request_id, self.target, self.context.expediente_id
        self._set_inputs(True)
        self._set_save("Guardando…", True)
        self._set_status("Guardando en el Calendario…", Q_MUTED)
        self._refresh()

        def work():
            create = (actions_service.create_task if self.kind == TASK
                      else actions_service.create_alert)
            try:
                result, error = create(self.actions.actor, target, request_id=request_id,
                                       expected_expediente_id=expected,
                                       db_path=self.actions.db_path, **values), ""
            except actions_service.DocumentActionError as exc:
                result, error = None, str(exc)
            except Exception:
                result, error = None, SAVE_FAILED

            def apply():
                # A closed viewer or form drops the result: the record (if any) stays intact.
                if self.closed or self.controller.closed:
                    return False
                self.sending = False
                if result is None:
                    self._set_inputs(False)
                    self._set_save("Guardar", False)
                    self._set_status(error, Q_ERROR)
                else:
                    self.result = result
                    self._set_status(self._confirmation(result), Q_SUCCESS)
                    self.save_button.visible = False
                    self.cancel_button.content.controls[-1].value = "Cerrar"
                _flush(self.page, self.dialog)
                return False

            self.controller.publish(apply)
            if result is not None and not self.controller.closed:
                self.controller.created(result)

        self.controller._run(work)
        return True

    def _confirmation(self, result):
        if self.kind == TASK:
            record = result["task"]
            when = actions_service.format_moment(record.get("fecha_vencimiento"))
            text = f"Tarea #{record['id']} creada en el Calendario · vence {when}."
        else:
            record = result["alert"]
            when = actions_service.format_moment(record.get("fecha_evento"))
            text = f"Aviso #{record['id']} creado en el Calendario · {when}."
        if not result.get("created"):
            text += " Ya estaba guardado: no se ha duplicado."
        return text

    # ------------------------------------------------------------------ lifecycle

    def show(self):
        _present_dialog(self.page, self.dialog)
        return self

    def close(self, e=None):
        """Cancel (no writes) or close after the result; the viewer stays as it was."""
        if self.closed:
            return
        self.closed = True
        _request_dismiss(self.page, self.dialog)
        if _contains(self.page.overlay, self.dialog):
            self.page.overlay.remove(self.dialog)
            self.page.update()
        else:
            _flush(self.page, self.dialog)
