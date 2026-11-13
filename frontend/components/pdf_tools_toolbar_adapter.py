"""Bind Viewer V2 requests to existing PDF Tools workflows, without file operations."""
from pathlib import Path

from backend.services.document_tools import pdf_tools_service
from backend.services.document_tools.safe_file_service import resolve_project_path
from frontend.components.app_button import secondary_button


PDF_ACTIONS = (
    ("rotate", "Rotar páginas"),
    ("move_page", "Mover página"),
    ("split", "Dividir PDF"),
    ("compress", "Comprimir PDF"),
    ("extract", "Extraer páginas"),
    ("merge", "Unir PDFs"),
    ("annotate", "Anotar PDF"),
)

ENABLED_TOOLTIP = "Genera una copia; conserva el original."
NO_PYPDF = "Falta la dependencia pypdf; las herramientas PDF no están disponibles."
NOT_PDF = "Las herramientas PDF solo están disponibles para documentos PDF."
NO_HANDLER = "Acción no disponible en este flujo."


class _PdfToolbar:
    """Seven PDF commands for the current document; disabled ones say why.

    Subclasses resolve the document identity (or the reason it has none);
    handlers own forms, validation, derived outputs, registration and feedback.
    DV29: _actions and DATA_PREFIX let the image tools reuse the same commands;
    with_image_tools() hands image documents to an image toolbar.
    DV29-WO-03: bind_selection() receives the viewer's multi-selection
    provider; the PDF commands ignore it, the image companion uses it.
    """

    DATA_PREFIX = ""

    def __init__(self, handlers, on_error, availability=None):
        self.handlers = dict(handlers)
        self.on_error = on_error
        self.availability = availability
        self.image_tools = None
        self.selection = None

    def with_image_tools(self, toolbar):
        """Companion toolbar for the documents it handles(path); returns self."""
        self.image_tools = toolbar
        if self.selection is not None:
            toolbar.bind_selection(self.selection)
        return self

    def bind_selection(self, provider):
        """provider() -> marked QueueDocuments in queue order, or None when the
        viewer offers no multi-selection (single mode, no comparator checkboxes)."""
        self.selection = provider
        if self.image_tools is not None:
            self.image_tools.bind_selection(provider)

    def selected_documents(self):
        if not callable(self.selection):
            return None
        try:
            documents = self.selection()
        except Exception:
            return None
        return None if documents is None else list(documents)

    def _image_document(self, path):
        return self.image_tools is not None and self.image_tools.handles(path)

    def tools_kind(self, path):
        """Tools kind the viewer titles: image for the companion's documents, else pdf."""
        return "image" if self._image_document(path) else "pdf"

    def _resolve(self, request):
        """(identity, None) when the document is eligible, else (None, reason)."""
        raise NotImplementedError

    def _call(self, handler, event, identity):
        raise NotImplementedError

    def _common_reason(self, request):
        if pdf_tools_service.PdfReader is None or pdf_tools_service.PdfWriter is None:
            return NO_PYPDF
        if Path(request.path).suffix.lower() != ".pdf":
            return NOT_PDF
        return None

    def _actions(self, request):
        """(operation, label) pairs in toolbar order."""
        return PDF_ACTIONS

    def __call__(self, request):
        if self._image_document(request.path):
            return self.image_tools(request)
        try:
            identity, reason = self._resolve(request)
        except Exception:
            identity, reason = None, "No se pudo comprobar el documento."
        reasons = {}
        if identity is not None and self.availability is not None:
            try:
                reasons = dict(self.availability(identity, request) or {})
            except Exception as exc:
                identity, reason = None, str(exc) or "No se pudo comprobar el documento."
        controls = []
        for operation, label in self._actions(request):
            handler = self.handlers.get(operation)
            disabled_reason = (reason if identity is None else
                               NO_HANDLER if not callable(handler) else reasons.get(operation))
            enabled = disabled_reason is None

            def invoke(event, handler=handler, expected=identity):
                try:
                    if expected is None or not callable(handler):
                        return
                    current, _ = self._resolve(request)
                    if current != expected:
                        raise ValueError("El documento ya no coincide con el visor. Vuelve a abrirlo.")
                    self._call(handler, event, expected)
                except Exception as exc:
                    self.on_error(exc)

            button = secondary_button(label, invoke if enabled else None)
            button.disabled = not enabled
            button.data = self.DATA_PREFIX + operation
            button.tooltip = ENABLED_TOOLTIP if enabled else disabled_reason
            controls.append(button)
        return controls


class PdfToolsToolbarAdapter(_PdfToolbar):
    """Callable toolbar factory for registered Bandeja items.

    resolve_item(request) must return the registered item for the current path.
    handlers receive (event, item_id=...), matching existing inbox dialogs.
    availability(item_id, request), optional, returns {operation: reason} for
    operations the document does not support (None means enabled).
    """

    def __init__(self, resolve_item, handlers, on_error, availability=None):
        super().__init__(handlers, on_error, availability)
        self.resolve_item = resolve_item

    def _resolve(self, request):
        reason = self._common_reason(request)
        if reason:
            return None, reason
        item = self.resolve_item(request)
        if not item or not item.get("id") or not item.get("stored_path"):
            return None, "El documento no está registrado en la Bandeja."
        if resolve_project_path(item["stored_path"]) != resolve_project_path(request.path):
            return None, "Esta copia no es el documento registrado en la Bandeja."
        return int(item["id"]), None

    def _item_id(self, request):
        return self._resolve(request)[0]

    def _call(self, handler, event, item_id):
        handler(event, item_id=item_id)


class ExpedientPdfToolsToolbar(_PdfToolbar):
    """Callable toolbar factory for documents of one expediente folder.

    validate(expediente_id, path) raises with a user-facing reason when the
    file is outside the expediente folder or not processable.
    handlers receive (event, path=..., expediente_id=...).
    availability((path, expediente_id), request) as in PdfToolsToolbarAdapter.
    """

    def __init__(self, expediente_id, validate, handlers, on_error, availability=None):
        super().__init__(handlers, on_error, availability)
        self.expediente_id = expediente_id
        self.validate = validate

    def _resolve(self, request):
        reason = self._common_reason(request)
        if reason:
            return None, reason
        if not self.expediente_id:
            return None, "Abre un expediente guardado para usar las herramientas PDF."
        try:
            self.validate(self.expediente_id, request.path)
        except Exception as exc:
            return None, str(exc) or "El documento no pertenece al expediente."
        return (str(Path(request.path).expanduser().resolve()), self.expediente_id), None

    def _call(self, handler, event, identity):
        path, expediente_id = identity
        handler(event, path=path, expediente_id=expediente_id)
