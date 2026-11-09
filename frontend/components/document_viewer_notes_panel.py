"""DV24-P2: "Notas y actividad" side panel of the active document.

Notes belong to the CRM (document_viewer_notes_service), never to the PDF
or to Box; no SQL or schema here. Each document keeps its own state, keyed
by its identity target, so changing the active document, group or mode
never mixes notes. Loads and submissions run off the UI thread and publish
only through the viewer's ``publish`` while the viewer is open: a closed
viewer drops late results.
"""
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime

import flet as ft

from backend.services import document_viewer_notes_service as notes_service
from frontend.components.document_viewer_modal import (
    Q_BORDER, Q_MUTED, Q_NAVY, Q_PRIMARY, Q_TEXT, Q_WHITE, _command,
)


PANEL_WIDTH = 340
COMPACT_PANEL_WIDTH = 296
RAIL_WIDTH = 52
GAP = 10

IDLE = "idle"
LOADING = "loading"
READY = "ready"
FAILED = "failed"

LOAD_FAILED = "No se pudieron cargar las notas."
SAVE_FAILED = "No se pudo guardar la nota."


@dataclass(frozen=True)
class ViewerNotes:
    """Notes context a view injects into the viewer.

    ``actor`` is the authenticated session user from the application
    boundary ({"id", "username"}); the service verifies it. Bandeja views
    add the (path, item id) pairs of their queue; expedient viewers rely on
    the viewer's expediente_id. ``run`` executes background work (default:
    a daemon thread); ``db_path`` is only for isolated tests.
    """
    actor: object = None
    inbox_items: tuple = ()
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


def target_key(target):
    if not target:
        return None
    if "inbox_item_id" in target:
        return f"inbox:{target['inbox_item_id']}"
    return f"expedient:{target['expediente_id']}:{target['path']}"


def format_timestamp(value):
    """dd/mm/YYYY HH:MM; UTC values are shown in local time, unknown text as is."""
    text = str(value or "").strip()
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return text or "—"
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%d/%m/%Y %H:%M")


class DocumentNotesState:
    """Notes, draft and pending submission of one document."""

    def __init__(self):
        self.status = IDLE
        self.token = 0
        self.data = None
        self.error = ""
        self.draft = ""
        self.request_id = None
        self.sending = False
        self.feedback = None  # (ok, text)


class NotesController:
    """Panel of the viewer's active document; lives as long as the viewer.

    ``publish(apply)`` is the viewer's: under its publication lock, while
    the viewer is live, it runs ``apply`` and flushes when it returns True.
    Every state change goes through it. ``on_resize`` lets the viewer
    re-lay out its canvas when the panel folds or unfolds.
    """

    def __init__(self, notes, *, expediente_id, compact, publish, on_resize=None):
        self.notes = notes
        self.expediente_id = expediente_id
        self.expanded_width = COMPACT_PANEL_WIDTH if compact else PANEL_WIDTH
        self.publish = publish
        self.on_resize = on_resize or (lambda: None)
        self.collapsed = False
        self.closed = False
        self.states = {}
        self.document = None
        self.target = None
        self.key = None
        self.height = 0
        self.container = None
        # Controls of the current render, for the viewer and tests.
        self.field = None
        self.send_button = None
        self.cancel_button = None
        self.retry_button = None
        self.toggle_button = None
        self.feedback_text = None
        self.note_cards = []

    @property
    def width(self):
        return RAIL_WIDTH if self.collapsed else self.expanded_width

    @property
    def space(self):
        """Width the canvas gives up for the panel."""
        return self.width + GAP

    @property
    def state(self):
        return self.states.get(self.key)

    # ------------------------------------------------------------------ viewer API

    def beside(self, canvas, document, height):
        """Canvas and the active document's panel side by side."""
        canvas.expand = True
        return ft.Row([canvas, self.build(document, height)], spacing=GAP,
                      vertical_alignment=ft.CrossAxisAlignment.START)

    def build(self, document, height):
        """Panel for the active document; the viewer holds its publication lock."""
        self.document = document
        self.target = self.notes.target(document, self.expediente_id)
        self.key = target_key(self.target) or f"unidentified:{getattr(document, 'key', '')}"
        self.states.setdefault(self.key, DocumentNotesState())
        self.height = height
        self.container = ft.Container(
            height=height, padding=12, border_radius=12, bgcolor=Q_WHITE,
            border=ft.Border.all(1, Q_BORDER), data="notes-panel",
        )
        self._render()
        if not self.collapsed:
            self._ensure_loaded()
        return self.container

    def close(self):
        """Viewer closed: pending loads and submissions are dropped."""
        self.closed = True

    # ------------------------------------------------------------------ work

    def _run(self, work):
        run = self.notes.run
        if callable(run):
            run(work)
        else:
            threading.Thread(target=work, daemon=True).start()

    def _ensure_loaded(self):
        state = self.state
        if self.target is not None and state is not None and state.status == IDLE:
            self._load(self.key)

    def _load(self, key):
        state, target = self.states[key], self.target
        state.status, state.error = LOADING, ""
        state.token += 1
        token = state.token
        self._render()

        def work():
            try:
                result, error = notes_service.load_document_notes(
                    self.notes.actor, target, db_path=self.notes.db_path), ""
            except notes_service.DocumentNotesError as exc:
                result, error = None, str(exc)
            except Exception:
                result, error = None, LOAD_FAILED

            def apply():
                if self.closed or state.token != token:
                    return False
                state.data, state.error = result, error
                state.status = READY if result is not None else FAILED
                return self._rerender(key)

            self.publish(apply)

        self._run(work)

    def _submit(self, key):
        state = self.states.get(key)
        if (self.closed or key != self.key or state is None or state.sending
                or state.status != READY):
            return False
        if self.field is not None and self.field.data == key:
            text = str(self.field.value or "")
            if text != state.draft:
                state.draft, state.request_id = text, None
        body, target = state.draft, self.target
        state.sending, state.feedback = True, None
        state.request_id = state.request_id or uuid.uuid4().hex
        request_id = state.request_id
        expected = state.data["identity"].content_sha256

        def work():
            try:
                note, error = notes_service.add_document_note(
                    self.notes.actor, target, body, request_id=request_id,
                    expected_sha256=expected, db_path=self.notes.db_path), ""
            except notes_service.DocumentNotesError as exc:
                note, error = None, str(exc)
            except Exception:
                note, error = None, SAVE_FAILED

            def apply():
                if self.closed:
                    return False
                state.sending = False
                if note is None:
                    # Same request_id on retry: a write that did happen is not duplicated.
                    state.feedback = (False, error)
                else:
                    notes = state.data["notes"]
                    if all(item["id"] != note["id"] for item in notes):
                        notes.insert(0, note)
                    state.draft, state.request_id = "", None
                    state.feedback = (True, "Nota añadida.")
                return self._rerender(key)

            self.publish(apply)

        self._run(work)
        return self._rerender(key)

    # ------------------------------------------------------------------ events

    def _event(self, action):
        def handler(e=None):
            if not self.closed:
                self.publish(action)
        return handler

    def _set_draft(self, key, value):
        state = self.states.get(key)
        if state is not None and not state.sending:
            state.draft = "" if value is None else str(value)
            state.request_id = None  # edited text is a new submission
        return False

    def _on_draft(self, key):
        def handler(e=None):
            value = getattr(getattr(e, "control", None), "value", None)
            if not self.closed:
                self.publish(lambda: self._set_draft(key, value))
        return handler

    def _cancel(self, key):
        state = self.states.get(key)
        if key != self.key or state is None or state.sending:
            return False
        state.draft, state.request_id, state.feedback = "", None, None
        return self._rerender(key)

    def _retry(self, key):
        state = self.states.get(key)
        if key != self.key or state is None or state.status == LOADING or self.target is None:
            return False
        state.status = IDLE
        self._load(key)
        return True

    def _toggle(self):
        self.collapsed = not self.collapsed
        self._render()
        if not self.collapsed:
            self._ensure_loaded()
        self.on_resize()
        return True

    # ------------------------------------------------------------------ rendering

    def _rerender(self, key):
        if key != self.key or self.container is None:
            return False
        self._render()
        return True

    def _render(self):
        self.field = self.send_button = self.cancel_button = None
        self.retry_button = self.feedback_text = None
        self.note_cards = []
        self.container.width = self.width
        self.container.padding = 6 if self.collapsed else 12
        self.container.content = self._rail() if self.collapsed else self._panel()

    def _rail(self):
        self.toggle_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT, icon_color=Q_PRIMARY, tooltip="Mostrar notas y actividad",
            on_click=self._event(self._toggle))
        state = self.state
        count = len(state.data["notes"]) if state and state.status == READY else None
        return ft.Column(
            tight=True, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self.toggle_button, ft.Icon(ft.Icons.EDIT_NOTE, color=Q_NAVY, size=22),
                      ft.Text("" if count is None else str(count), size=12, color=Q_MUTED)],
        )

    def _panel(self):
        self.toggle_button = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT, icon_color=Q_PRIMARY, tooltip="Plegar panel de notas",
            on_click=self._event(self._toggle))
        document = self.document
        name = getattr(document, "name", "") or "Sin documento"
        controls = [
            ft.Row(spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.Icons.EDIT_NOTE, color=Q_NAVY, size=20),
                ft.Text("Notas y actividad", size=15, weight=ft.FontWeight.BOLD, color=Q_NAVY),
                ft.Container(expand=True),
                self.toggle_button,
            ]),
            ft.Text(name, size=13, weight=ft.FontWeight.W_600, color=Q_TEXT, max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=getattr(document, "path", None) or None),
        ]
        state = self.state
        if self.target is None:
            controls.append(_alert(notes_service.NO_IDENTITY))
        elif state.status in (IDLE, LOADING):
            controls.append(ft.Row(spacing=8, controls=[
                ft.ProgressRing(width=18, height=18),
                ft.Text("Cargando notas…", size=12, color=Q_MUTED)]))
        elif state.status == FAILED:
            self.retry_button = _command("Reintentar", self._event(lambda k=self.key: self._retry(k)),
                                         icon=ft.Icons.REFRESH, height=36)
            controls += [_alert(state.error or LOAD_FAILED), self.retry_button]
        else:
            controls += self._ready(state)
        return ft.Column(controls=controls, spacing=8, scroll=ft.ScrollMode.AUTO)

    def _ready(self, state):
        key, data = self.key, state.data
        identity, notes = data["identity"], data["notes"]
        controls = [
            ft.Text(identity.label, size=11, color=Q_MUTED, max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS, tooltip=identity.label),
            _section(f"NOTAS ({len(notes)})"),
        ]
        if data.get("other_revisions"):
            controls.append(_info(
                f"{data['other_revisions']} nota(s) de una versión anterior de este archivo no se "
                "muestran: su contenido ha cambiado."))
        self.note_cards = [_note_card(note) for note in notes]
        controls += self.note_cards or [
            ft.Text("Todavía no hay notas para este documento.", size=12, color=Q_MUTED)]

        self.field = ft.TextField(
            label="Añadir nota", value=state.draft, multiline=True, min_lines=3, max_lines=6,
            max_length=notes_service.MAX_NOTE_LENGTH, text_size=13, disabled=state.sending,
            on_change=self._on_draft(key), data=key)
        self.cancel_button = _command("Cancelar", self._event(lambda: self._cancel(key)),
                                      height=36, disabled=state.sending)
        self.send_button = _command("Enviando…" if state.sending else "Enviar",
                                    self._event(lambda: self._submit(key)), icon=ft.Icons.SEND,
                                    primary=True, height=36, disabled=state.sending)
        controls += [
            self.field,
            ft.Row([ft.Container(expand=True), self.cancel_button, self.send_button], spacing=8),
            ft.Text(f"Autor: {data['user']['username']} (sesión actual)", size=11, color=Q_MUTED),
        ]
        if state.feedback:
            ok, text = state.feedback
            self.feedback_text = ft.Text(text, size=12, color="#027A48" if ok else "#B42318")
            controls.append(self.feedback_text)

        controls.append(_section("ACTIVIDAD"))
        if identity.description:
            controls.append(_info(f"Descripción de Bandeja: {identity.description}"))
        if data.get("activity_error"):
            controls.append(_alert(data["activity_error"]))
        events = data.get("activity") or []
        controls += [_event_row(event) for event in events] or [
            ft.Text("Sin actividad registrada.", size=12, color=Q_MUTED)]
        return controls


# ---------------------------------------------------------------------- builders


def _section(title):
    return ft.Text(title, size=10.5, weight=ft.FontWeight.W_700, color=Q_NAVY)


def _alert(text):
    return ft.Container(
        padding=10, border_radius=8, bgcolor="#FEF3F2", border=ft.Border.all(1, "#FECDCA"),
        content=ft.Text(text, size=12, color="#B42318"),
    )


def _info(text):
    return ft.Container(
        padding=8, border_radius=8, bgcolor="#F0F9FF", border=ft.Border.all(1, "#B9E6FE"),
        content=ft.Text(text, size=12, color="#026AA2"),
    )


def _note_card(note):
    # Plain, selectable text: the note is never interpreted as markup.
    return ft.Container(
        padding=10, border_radius=8, bgcolor="#F8FAFC", border=ft.Border.all(1, Q_BORDER),
        data=f"note:{note['id']}",
        content=ft.Column(spacing=4, controls=[
            ft.Row(spacing=6, controls=[
                ft.Icon(ft.Icons.PERSON_OUTLINE, size=16, color=Q_MUTED),
                ft.Text(note["author_username"], size=12, weight=ft.FontWeight.W_600, color=Q_TEXT),
                ft.Container(expand=True),
                ft.Text(format_timestamp(note["created_at"]), size=11, color=Q_MUTED),
            ]),
            ft.Text(note["body"], size=13, color=Q_TEXT, selectable=True),
        ]),
    )


def _event_row(event):
    return ft.Row(spacing=6, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
        ft.Icon(ft.Icons.HISTORY, size=16, color=Q_MUTED),
        ft.Column(spacing=0, expand=True, controls=[
            ft.Text(event["message"] or event["type"] or "Evento", size=12, color=Q_TEXT),
            ft.Text(f"{format_timestamp(event['at'])} · {event['source']}", size=11, color=Q_MUTED),
        ]),
    ])
