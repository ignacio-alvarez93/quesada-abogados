"""Forms of the seven viewer PDF tools, shared by Bandeja and Expedientes.

Each form asks for its parameters, runs document_viewer_tools_service and
shows success or error inside itself: the viewer stays open on top of the
calling view, so feedback in that view would be hidden. No file operations
or persistence here.
"""
import threading
from pathlib import Path

import flet as ft

from backend.services.document_tools import document_viewer_tools_service as tools
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.document_viewer_modal import (
    _contains, _flush, _present_dialog, _request_dismiss,
)
from frontend.components.pdf_tools_toolbar_adapter import (
    PDF_ACTIONS, ExpedientPdfToolsToolbar, PdfToolsToolbarAdapter,
)


Q_TEXT = "#1E293B"
Q_MUTED = "#64748B"
Q_SUCCESS = "#027A48"
Q_ERROR = "#B42318"

TOOL_LABELS = dict(PDF_ACTIONS)

SUBMIT_LABELS = {
    "rotate": "Rotar páginas",
    "move_page": "Mover página",
    "split": "Dividir PDF",
    "compress": "Comprimir",
    "extract": "Extraer páginas",
    "merge": "Unir PDFs",
    "annotate": "Guardar nota",
}

NON_DESTRUCTIVE = "Se generará una copia nueva registrada en la Bandeja; el PDF original no se modifica."


class PdfToolForm:
    """One open tool form; ``dialog`` is presented above the viewer."""

    def __init__(self, tools_ui, operation, scope):
        self.tools_ui = tools_ui
        self.page = tools_ui.page
        self.operation = operation
        self.scope = scope
        self.fields = {}
        self.order = ["current"]
        self.checks = {}
        self.outcome = None
        self.closed = False
        self._busy = threading.Lock()

        self.status = ft.Text("", size=12, color=Q_MUTED, selectable=True)
        self.submit_button = primary_button(SUBMIT_LABELS[operation], self.submit)
        self.cancel_button = secondary_button("Cancelar", self.close)
        self.order_column = ft.Column(spacing=4, tight=True)

        origin = (f"Bandeja #{scope.inbox_item_id}" if scope.kind == "inbox"
                  else f"Expediente {scope.expediente_id} · {scope.relative_path}")
        body = [
            ft.Text(scope.name, size=13, weight=ft.FontWeight.W_600, color=Q_TEXT,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=scope.source_path),
            ft.Text(f"{origin} · {scope.page_count} página(s)", size=11, color=Q_MUTED),
            *self._build_fields(),
            ft.Text(NON_DESTRUCTIVE, size=11, color=Q_MUTED),
            self.status,
        ]
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(TOOL_LABELS[operation]),
            content=ft.Container(width=460, content=ft.Column(body, tight=True, spacing=8,
                                                               scroll=ft.ScrollMode.AUTO)),
            actions=[self.cancel_button, self.submit_button],
            actions_alignment=ft.MainAxisAlignment.END,
            data=self,
        )

    # ------------------------------------------------------------------ fields

    def _field(self, name, label, hint, width=200, **kwargs):
        control = ft.TextField(label=label, hint_text=hint, width=width, **kwargs)
        self.fields[name] = control
        return control

    def _build_fields(self):
        count = self.scope.page_count
        op = self.operation
        if op == "rotate":
            degrees = ft.Dropdown(label="Rotación", width=160, value="90", options=[
                ft.dropdown.Option("90", "90° derecha"),
                ft.dropdown.Option("180", "180°"),
                ft.dropdown.Option("270", "90° izquierda"),
            ])
            self.fields["degrees"] = degrees
            return [ft.Row([self._field("pages", "Página(s) a rotar", f"Ej.: 1,3,5-{count}", 220), degrees],
                           spacing=8, wrap=True),
                    ft.Text("Una página, varias o rangos: 1 · 1,3 · 2-4.", size=11, color=Q_MUTED)]
        if op == "move_page":
            return [ft.Row([self._field("page_number", "Página a mover", f"1-{count}", 160),
                            self._field("target_position", "Nueva posición", f"1-{count}", 160)],
                           spacing=8, wrap=True)]
        if op == "split":
            return [self._field("ranges", "Rangos", f"Ej.: 1-2,3-{count}", 320),
                    ft.Text("Cada rango inclusivo genera un PDF independiente.", size=11, color=Q_MUTED)]
        if op == "extract":
            return [self._field("pages", "Páginas a extraer", "Ej.: 1,3,5-7", 320),
                    ft.Text("Las páginas se copian en el orden indicado a un PDF nuevo.",
                            size=11, color=Q_MUTED)]
        if op == "compress":
            return [ft.Text("¿Generar una copia comprimida? Si no reduce el tamaño, no se crea "
                            "ningún archivo.", size=12, color=Q_TEXT),
                    ft.Text("Se conserva la opción más pequeña; si es la rasterizada, la copia "
                            "pierde el texto seleccionable.", size=11, color=Q_MUTED)]
        if op == "annotate":
            position = ft.Dropdown(label="Posición", width=180, value="top", options=[
                ft.dropdown.Option("top", "Margen superior"),
                ft.dropdown.Option("bottom", "Margen inferior"),
            ])
            self.fields["position"] = position
            return [ft.Row([self._field("page_number", "Página", f"1-{count}", 120,
                                        value=str(self.tools_ui.page_hint(count))), position],
                           spacing=8, wrap=True),
                    self._field("text", "Texto de la nota", "Escribe la anotación", 440,
                                multiline=True, min_lines=2, max_lines=5,
                                max_length=tools.pdf_tools.ANNOTATION_MAX_CHARS),
                    ft.Text("Nota de texto en el margen elegido. La edición visual libre no "
                            "está incluida.", size=11, color=Q_MUTED)]
        # merge
        candidates = []
        for candidate in self.scope.merge_candidates:
            check = ft.Checkbox(label=candidate["name"], value=False, data=candidate["key"],
                                on_change=lambda e, key=candidate["key"]: self.toggle(key))
            self.checks[candidate["key"]] = check
            candidates.append(check)
        self._render_order()
        source = "del mismo expediente" if self.scope.kind == "expedient" else "de la Bandeja con la misma vinculación"
        return [ft.Text(f"PDF disponibles {source}:", size=12, color=Q_TEXT),
                ft.Container(height=min(180, 36 * max(1, len(candidates))),
                             content=ft.Column(candidates, spacing=0, scroll=ft.ScrollMode.AUTO)),
                ft.Text("Orden de unión:", size=12, color=Q_TEXT),
                self.order_column]

    # ------------------------------------------------------------------ merge order

    def _label(self, key):
        if key == "current":
            return f"{self.scope.name} (documento abierto)"
        return next(c["name"] for c in self.scope.merge_candidates if c["key"] == key)

    def _render_order(self):
        rows = []
        for index, key in enumerate(self.order):
            rows.append(ft.Row(spacing=4, controls=[
                ft.Text(f"{index + 1}. {self._label(key)}", size=12, expand=True,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=16, tooltip="Subir",
                              disabled=index == 0, on_click=lambda e, k=key: self.move(k, -1)),
                ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=16, tooltip="Bajar",
                              disabled=index == len(self.order) - 1,
                              on_click=lambda e, k=key: self.move(k, 1)),
            ]))
        self.order_column.controls = rows

    def toggle(self, key):
        if key in self.order:
            self.order.remove(key)
        else:
            self.order.append(key)
        if key in self.checks:
            self.checks[key].value = key in self.order
        self._render_order()
        self._refresh()

    def move(self, key, offset):
        index = self.order.index(key)
        target = index + offset
        if 0 <= target < len(self.order):
            self.order[index], self.order[target] = self.order[target], self.order[index]
            self._render_order()
            self._refresh()

    # ------------------------------------------------------------------ lifecycle

    def params(self):
        values = {name: control.value for name, control in self.fields.items()}
        if self.operation == "merge":
            values["order"] = list(self.order)
        return values

    def _refresh(self):
        if not self.closed:
            _flush(self.page, self.dialog)

    def _set_status(self, text, color):
        self.status.value = text
        self.status.color = color
        self._refresh()

    def _run(self):
        return tools.run_tool(self.scope, self.operation, self.params(),
                              inbox_items=self.tools_ui.inbox_items())

    def _message(self, outcome):
        return success_message(outcome)

    def submit(self, e=None):
        if self.closed or self.outcome is not None or not self._busy.acquire(blocking=False):
            return None
        try:
            self.submit_button.disabled = True
            self._set_status("Procesando…", Q_MUTED)
            try:
                outcome = self._run()
            except Exception as exc:
                self.submit_button.disabled = False
                self._set_status(f"No se pudo completar: {exc}", Q_ERROR)
                return None
            self.outcome = outcome
            self.submit_button.visible = False
            self.cancel_button.content.value = "Cerrar"
            self._set_status(self._message(outcome), Q_SUCCESS)
            self.tools_ui.done(outcome)
            return outcome
        finally:
            self._busy.release()

    def show(self):
        _present_dialog(self.page, self.dialog)
        return self

    def close(self, e=None):
        if self.closed:
            return
        self.closed = True
        _request_dismiss(self.page, self.dialog)
        if _contains(self.page.overlay, self.dialog):
            self.page.overlay.remove(self.dialog)
            self.page.update()
        else:
            _flush(self.page, self.dialog)
        self.tools_ui.forget(self)


def success_message(outcome):
    generated = [f"#{item.get('id')}" for item in outcome.get("generated_items") or [] if item.get("id")]
    names = [Path(path).name for path in outcome.get("outputs") or []]
    label = TOOL_LABELS.get(outcome.get("operation"), "Operación")
    lines = [f"{label}: completado. Original intacto."]
    if generated:
        lines.append(f"Nuevo(s) documento(s) en la Bandeja: {', '.join(generated)}.")
    if names:
        lines.append("Archivo(s): " + ", ".join(names))
    return "\n".join(lines)


class ViewerPdfTools:
    """Toolbar factories and forms of the viewer PDF tools for one calling view.

    on_done(outcome) lets the caller refresh its listings; on_error(exc)
    reports problems that happen before a form opens. inbox_items() returns
    the Bandeja items currently listed (merge candidates for Bandeja).
    """

    TITLE = "Herramientas PDF"

    def __init__(self, page, *, on_done=None, on_error=None, inbox_items=None):
        self.page = page
        self.on_done = on_done
        self.on_error = on_error or (lambda exc: None)
        self._inbox_items = inbox_items or (lambda: ())
        self._cache = {}
        self.forms = []
        self.notices = []
        self.current_page = 1

    def inbox_items(self):
        try:
            return list(self._inbox_items() or ())
        except Exception:
            return []

    def page_hint(self, page_count):
        return max(1, min(int(self.current_page or 1), page_count))

    # ------------------------------------------------------------------ scopes

    def _cached(self, key, path, build):
        """Scope reused while the file is unchanged: toolbars rebuild on every scroll."""
        try:
            stat = Path(path).stat()
        except OSError as exc:
            raise tools.ToolScopeError("El documento no existe.") from exc
        stamp = (stat.st_mtime_ns, stat.st_size)
        hit = self._cache.get(key)
        if hit is None or hit[0] != stamp:
            try:
                value = build()
            except tools.ToolScopeError as exc:
                value = exc
            self._cache[key] = hit = (stamp, value)
        if isinstance(hit[1], Exception):
            raise hit[1]
        return hit[1]

    def _inbox_key(self, item_id, path):
        ids = tuple(sorted(str(item.get("id")) for item in self.inbox_items()))
        return ("inbox", int(item_id), str(path), ids)

    def inbox_availability(self, item_id, request):
        self.current_page = request.page_number
        scope = self._cached(self._inbox_key(item_id, request.path), request.path,
                             lambda: tools.inbox_scope(item_id, request.path, inbox_items=self.inbox_items()))
        return tools.availability(scope)

    def expedient_scope_cached(self, expediente_id, path):
        return self._cached(("expedient", str(expediente_id), str(path)), path,
                            lambda: tools.expedient_scope(expediente_id, path))

    def expedient_availability(self, identity, request):
        self.current_page = request.page_number
        path, expediente_id = identity
        return tools.availability(self.expedient_scope_cached(expediente_id, path))

    # ------------------------------------------------------------------ toolbars

    def inbox_toolbar(self, resolve_item):
        handlers = {
            op: (lambda e, item_id, op=op: self.open(op, lambda: tools.inbox_scope(
                item_id, inbox_items=self.inbox_items())))
            for op in tools.OPERATIONS
        }
        return PdfToolsToolbarAdapter(resolve_item, handlers, self.report,
                                      availability=self.inbox_availability)

    def expedient_toolbar(self, expediente_id):
        handlers = {
            op: (lambda e, path, expediente_id, op=op: self.open(
                op, lambda: tools.expedient_scope(expediente_id, path)))
            for op in tools.OPERATIONS
        }
        return ExpedientPdfToolsToolbar(expediente_id, self.expedient_scope_cached, handlers,
                                        self.report, availability=self.expedient_availability)

    # ------------------------------------------------------------------ forms

    def report(self, exc):
        """Error before any form opens: visible above the viewer, then the caller's handler."""
        notice = ft.AlertDialog(modal=True, title=ft.Text(self.TITLE),
                                content=ft.Text(str(exc), color=Q_ERROR, selectable=True))

        def dismiss(e=None):
            if notice not in self.notices:
                return
            self.notices.remove(notice)
            _request_dismiss(self.page, notice)
            if _contains(self.page.overlay, notice):
                self.page.overlay.remove(notice)
                self.page.update()
            else:
                _flush(self.page, notice)

        notice.actions = [secondary_button("Cerrar", dismiss)]
        self.notices.append(notice)
        try:
            _present_dialog(self.page, notice)
        finally:
            self.on_error(exc)

    def _form(self, operation, scope):
        reason = tools.availability(scope).get(operation)
        if reason:
            raise ValueError(reason)
        return PdfToolForm(self, operation, scope)

    def open(self, operation, build_scope):
        """Fresh scope validation, then the form; errors are reported visibly."""
        try:
            form = self._form(operation, build_scope())
        except Exception as exc:
            self.report(exc)
            return None
        self.forms.append(form)
        return form.show()

    def forget(self, form):
        self.forms = [item for item in self.forms if item is not form]

    def done(self, outcome):
        self._cache.clear()
        if self.on_done:
            try:
                self.on_done(outcome)
            except Exception as exc:
                self.on_error(exc)
