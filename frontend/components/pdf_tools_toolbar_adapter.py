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


class PdfToolsToolbarAdapter:
    """Callable toolbar factory; missing workflows stay disabled.

    resolve_item(request) must return the registered item for the current path.
    handlers receive (event, item_id=...), matching existing inbox dialogs.
    Those dialogs own validation, derived outputs, registration and feedback.
    """

    def __init__(self, resolve_item, handlers, on_error):
        self.resolve_item = resolve_item
        self.handlers = dict(handlers)
        self.on_error = on_error

    def _item_id(self, request):
        if pdf_tools_service.PdfReader is None or pdf_tools_service.PdfWriter is None:
            return None
        if Path(request.path).suffix.lower() != ".pdf":
            return None
        item = self.resolve_item(request)
        if not item or not item.get("id") or not item.get("stored_path"):
            return None
        if resolve_project_path(item["stored_path"]) != resolve_project_path(request.path):
            return None
        return int(item["id"])

    def __call__(self, request):
        try:
            item_id = self._item_id(request)
        except Exception:
            item_id = None
        controls = []
        for operation, label in PDF_ACTIONS:
            handler = self.handlers.get(operation)
            enabled = item_id is not None and callable(handler)

            def invoke(event, handler=handler, expected=item_id):
                try:
                    if expected is None or not callable(handler):
                        return
                    if self._item_id(request) != expected:
                        raise ValueError("El documento ya no coincide con el visor. Vuelve a abrirlo.")
                    handler(event, item_id=expected)
                except Exception as exc:
                    self.on_error(exc)

            button = secondary_button(label, invoke if enabled else None)
            button.disabled = not enabled
            button.tooltip = "Genera una copia; conserva el original." if enabled else "No disponible para este documento o flujo."
            controls.append(button)
        return controls
