"""Forms and toolbar of the six viewer JPG/PNG tools, shared by Bandeja and Expedientes.

Same lifecycle as the PDF tools (document_viewer_pdf_tools): each form asks
for its parameters, runs document_viewer_image_tools_service and shows
success or error inside itself, above the viewer. A PDF toolbar hands
image documents to these commands through with_image_tools(): JPG/JPEG/PNG
get the six tools, other image formats the reason they are not editable.
Non-image documents keep the PDF commands. No file operations or
persistence here.
"""
import threading
from pathlib import Path

import flet as ft

from backend.services import document_viewer_service
from backend.services.document_tools import document_viewer_image_tools_service as tools
from backend.services.document_tools import image_tools_service as image_tools
from frontend.components.app_button import primary_button, secondary_button
from frontend.components.document_viewer_pdf_tools import (
    Q_MUTED, Q_TEXT, PdfToolForm, ViewerPdfTools,
)
from frontend.components.pdf_tools_toolbar_adapter import (
    ExpedientPdfToolsToolbar, PdfToolsToolbarAdapter,
)


NOT_IMAGE = "Las herramientas de imagen solo están disponibles para JPG, JPEG o PNG."
NO_PILLOW = "Falta la dependencia Pillow; las herramientas de imagen no están disponibles."
NO_EXPEDIENT = "Abre un expediente guardado para usar las herramientas de imagen."

FORMAT_NAMES = {"JPEG": "JPG", "PNG": "PNG"}

FORM_TITLES = {
    "rotate": "Rotar imagen",
    "crop": "Recortar imagen",
    "resize": "Redimensionar imagen",
    "optimize": "Optimizar / comprimir imagen",
    "convert": "Convertir JPG ↔ PNG",
    "to_pdf": "Convertir imagen a PDF",
}

SUBMIT_LABELS = {
    "rotate": "Rotar",
    "crop": "Recortar",
    "resize": "Redimensionar",
    "optimize": "Optimizar",
    "convert": "Convertir",
    "to_pdf": "Convertir a PDF",
}

NON_DESTRUCTIVE = "Se generará una copia nueva registrada en la Bandeja; la imagen original no se modifica."


def is_editable_image(path):
    return Path(str(path or "")).suffix.lower() in image_tools.EDITABLE_IMAGE_FORMATS


def image_actions(path):
    """Six (operation, label) commands; the conversion names its real target."""
    target = "JPG" if Path(str(path or "")).suffix.lower() == ".png" else "PNG"
    return (
        ("rotate", "Rotar"),
        ("crop", "Recortar"),
        ("resize", "Redimensionar"),
        ("optimize", "Optimizar"),
        ("convert", f"Convertir a {target}"),
        ("to_pdf", "Convertir a PDF"),
    )


def human_size(size):
    size = int(size or 0)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB".replace(".", ",")
    return f"{size / 1048576:.2f} MB".replace(".", ",")


def describe(scope):
    parts = [FORMAT_NAMES.get(scope.format, scope.format), f"{scope.width} × {scope.height} px",
             human_size(scope.size_bytes)]
    if scope.has_alpha:
        parts.append("con transparencia")
    if scope.exif_orientation != 1:
        parts.append("orientación EXIF aplicada")
    return " · ".join(parts)


# --------------------------------------------------------------------------- toolbars

class _ImageCommands:
    """Image variant of the PDF adapters: same guards, six image commands."""

    DATA_PREFIX = "image_"

    def handles(self, path):
        # Every image the viewer previews: GIF, BMP... say why they are not editable.
        return Path(str(path or "")).suffix.lower() in document_viewer_service.IMAGE_EXTENSIONS

    def tools_kind(self, path):
        return "image"

    def _common_reason(self, request):
        if image_tools.Image is None:
            return NO_PILLOW
        if not is_editable_image(request.path):
            return NOT_IMAGE
        return None

    def _actions(self, request):
        return image_actions(request.path)


class InboxImageToolbar(_ImageCommands, PdfToolsToolbarAdapter):
    """Image commands for registered Bandeja items; contract of PdfToolsToolbarAdapter."""


class ExpedientImageToolbar(_ImageCommands, ExpedientPdfToolsToolbar):
    """Image commands for one expediente folder; contract of ExpedientPdfToolsToolbar."""

    def _resolve(self, request):
        if not self.expediente_id and self._common_reason(request) is None:
            return None, NO_EXPEDIENT
        return super()._resolve(request)


# --------------------------------------------------------------------------- forms

class ImageToolForm(PdfToolForm):
    """One open image tool form; lifecycle (submit guard, close) is PdfToolForm's."""

    def __init__(self, tools_ui, operation, scope):
        self.tools_ui = tools_ui
        self.page = tools_ui.page
        self.operation = operation
        self.scope = scope
        self.fields = {}
        self.fixed = {}
        self.outcome = None
        self.closed = False
        self._busy = threading.Lock()
        self.dialog = None

        self.status = ft.Text("", size=12, color=Q_MUTED, selectable=True)
        self.preview = ft.Text("", size=12, color=Q_TEXT)
        self.submit_button = primary_button(SUBMIT_LABELS[operation], self.submit)
        self.cancel_button = secondary_button("Cancelar", self.close)

        origin = (f"Bandeja #{scope.inbox_item_id}" if scope.kind == "inbox"
                  else f"Expediente {scope.expediente_id} · {scope.relative_path}")
        body = [
            ft.Text(scope.name, size=13, weight=ft.FontWeight.W_600, color=Q_TEXT,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=scope.source_path),
            ft.Text(origin, size=11, color=Q_MUTED),
            ft.Text(f"Original: {describe(scope)}", size=11, color=Q_MUTED),
            *self._build_fields(),
            self.preview,
            ft.Text(NON_DESTRUCTIVE, size=11, color=Q_MUTED),
            self.status,
        ]
        self.update_preview()
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(FORM_TITLES[operation]),
            content=ft.Container(width=460, content=ft.Column(body, tight=True, spacing=8,
                                                               scroll=ft.ScrollMode.AUTO)),
            actions=[self.cancel_button, self.submit_button],
            actions_alignment=ft.MainAxisAlignment.END,
            data=self,
        )

    # ------------------------------------------------------------------ fields

    def _changed(self, e=None):
        self.update_preview()
        self._refresh()

    def _field(self, name, label, hint, width=200, **kwargs):
        control = ft.TextField(label=label, hint_text=hint, width=width,
                               keyboard_type=ft.KeyboardType.NUMBER, on_change=self._changed, **kwargs)
        self.fields[name] = control
        return control

    def _build_fields(self):
        scope = self.scope
        op = self.operation
        if op == "rotate":
            degrees = ft.Dropdown(label="Rotación", width=180, value="90", options=[
                ft.dropdown.Option("90", "90° derecha"),
                ft.dropdown.Option("180", "180°"),
                ft.dropdown.Option("270", "90° izquierda"),
            ])
            # The selection event is on_select in recent Flet, on_change before.
            for event in ("on_select", "on_change"):
                if hasattr(degrees, event):
                    setattr(degrees, event, self._changed)
            self.fields["degrees"] = degrees
            return [degrees]
        if op == "crop":
            return [
                ft.Row([self._field("left", "Izquierda (px)", f"0-{scope.width - 1}", 105, value="0"),
                        self._field("top", "Arriba (px)", f"0-{scope.height - 1}", 105, value="0"),
                        self._field("right", "Derecha (px)", f"1-{scope.width}", 105, value=str(scope.width)),
                        self._field("bottom", "Abajo (px)", f"1-{scope.height}", 105,
                                    value=str(scope.height))],
                       spacing=8, wrap=True),
                ft.Text("Recorte por coordenadas en píxeles sobre la imagen tal como se ve: (0, 0) es la "
                        "esquina superior izquierda; Derecha y Abajo son bordes exclusivos.",
                        size=11, color=Q_MUTED),
            ]
        if op == "resize":
            return [
                ft.Row([self._field("width", "Ancho (px)", f"Actual: {scope.width}", 150),
                        self._field("height", "Alto (px)", f"Actual: {scope.height}", 150)],
                       spacing=8, wrap=True),
                ft.Text("Se conserva la proporción: la imagen se ajusta dentro del ancho y/o alto "
                        "indicados.", size=11, color=Q_MUTED),
            ]
        if op == "optimize":
            if scope.format == "JPEG":
                low, high = image_tools.JPEG_QUALITY_RANGE
                return [
                    self._field("quality", "Calidad JPG", f"{low}-{high}", 150,
                                value=str(image_tools.DEFAULT_JPEG_QUALITY)),
                    ft.Text(f"Recompresión con pérdida, calidad entre {low} y {high}. Menos calidad suele "
                            "ocupar menos, pero no está garantizado.", size=11, color=Q_MUTED),
                ]
            return [ft.Text("Recompresión PNG sin pérdida: los píxeles y la transparencia no cambian.",
                            size=12, color=Q_TEXT)]
        if op == "convert":
            target = "jpg" if scope.format == "PNG" else "png"
            self.fixed["target_format"] = target
            return [ft.Text(f"Conversión de {FORMAT_NAMES[scope.format]} a {target.upper()}.",
                            size=12, color=Q_TEXT)]
        # to_pdf
        return [ft.Text("PDF de una página con la imagen tal como se ve en el visor.",
                        size=12, color=Q_TEXT)]

    # ------------------------------------------------------------------ preview

    def _value(self, name):
        text = str(self.fields[name].value or "").strip()
        return int(text) if text.lstrip("-").isdigit() else None

    def explain(self):
        """Expected result for the current parameters; the service validates for real."""
        scope = self.scope
        w, h = scope.width, scope.height
        op = self.operation
        flatten = ("La transparencia se rellenará de blanco "
                   f"({image_tools.JPEG_BACKGROUND_HEX}).") if scope.has_alpha else ""
        if op == "rotate":
            degrees = str(self.fields["degrees"].value or "")
            size = (h, w) if degrees in ("90", "270") else (w, h)
            return f"Resultado: {size[0]} × {size[1]} px."
        if op == "crop":
            left, top, right, bottom = (self._value(n) for n in ("left", "top", "right", "bottom"))
            if None in (left, top, right, bottom):
                return "Indica las cuatro coordenadas en píxeles enteros."
            if left < 0 or top < 0 or right > w or bottom > h:
                return f"Fuera de límites: la imagen mide {w} × {h} px."
            if left >= right or top >= bottom:
                return "Izquierda debe ser menor que Derecha y Arriba menor que Abajo."
            if (left, top, right, bottom) == (0, 0, w, h):
                return "El recorte abarca toda la imagen; ajusta las coordenadas."
            return f"Resultado: {right - left} × {bottom - top} px desde ({left}, {top})."
        if op == "resize":
            target_w, target_h = self._value("width"), self._value("height")
            if not target_w and not target_h:
                return "Indica el ancho, el alto o ambos."
            if (target_w is not None and target_w < 1) or (target_h is not None and target_h < 1):
                return "Las medidas deben ser mayores que cero."
            scale = min(s for s in (target_w and target_w / w, target_h and target_h / h) if s)
            return f"Resultado: {max(1, round(w * scale))} × {max(1, round(h * scale))} px."
        if op == "optimize":
            return (f"Tamaño original: {human_size(scope.size_bytes)}. Si la copia no resulta más "
                    "pequeña, no se crea ningún archivo.")
        if op == "convert":
            if scope.format == "JPEG":
                return "Se generará un PNG sin pérdida; suele ocupar más que el JPG."
            if scope.has_alpha:
                return f"JPG no admite transparencia. {flatten}"
            return f"Se generará un JPG de calidad {image_tools.DERIVED_JPEG_QUALITY}."
        return " ".join(filter(None, [f"Página de {w} × {h} px.", flatten]))

    def update_preview(self):
        self.preview.value = self.explain()

    # ------------------------------------------------------------------ lifecycle

    def params(self):
        values = {name: control.value for name, control in self.fields.items()}
        values.update(self.fixed)
        return values

    def _run(self):
        if self.operation == "crop" and self.explain().startswith("El recorte abarca toda"):
            raise ValueError("El recorte abarca toda la imagen; ajusta las coordenadas.")
        return tools.run_image_tool(self.scope, self.operation, self.params())

    def _message(self, outcome):
        return image_success_message(outcome)

    def _refresh(self):
        if self.dialog is not None:
            super()._refresh()


def image_success_message(outcome):
    operation = outcome.get("operation")
    metadata = (((outcome.get("response") or {}).get("result") or {}).get("metadata")) or {}
    outputs = outcome.get("outputs") or []
    lines = [f"{FORM_TITLES.get(operation, 'Operación')}: completado. Original intacto."]
    if operation == "optimize":
        before = metadata.get("source_size_bytes")
        after = metadata.get("size_bytes")
        if after is None and outputs:
            after = Path(outputs[0]).stat().st_size
        if before and after is not None:
            lines.append(f"Tamaño original: {human_size(before)} · tamaño final: {human_size(after)} "
                         f"({(after - before) / before * 100:+.0f} %).")
    if metadata.get("output_width") and metadata.get("output_height"):
        lines.append(f"Resultado: {metadata['output_width']} × {metadata['output_height']} px.")
    generated = [f"#{item.get('id')}" for item in outcome.get("generated_items") or [] if item.get("id")]
    if generated:
        lines.append(f"Nuevo documento en la Bandeja: {', '.join(generated)}.")
    if outputs:
        lines.append("Archivo: " + ", ".join(Path(path).name for path in outputs))
    return "\n".join(lines)


# --------------------------------------------------------------------------- calling view

class ViewerImageTools(ViewerPdfTools):
    """Toolbar factories and forms of the viewer image tools for one calling view.

    on_done(outcome) lets the caller refresh its listings; on_error(exc)
    reports problems that happen before a form opens.
    """

    TITLE = "Herramientas de imagen"

    def __init__(self, page, *, on_done=None, on_error=None):
        super().__init__(page, on_done=on_done, on_error=on_error)

    # ------------------------------------------------------------------ scopes

    def inbox_scope_cached(self, item_id, path):
        return self._cached(("image-inbox", int(item_id), str(path)), path,
                            lambda: tools.inbox_image_scope(item_id, path))

    def inbox_availability(self, item_id, request):
        return tools.availability(self.inbox_scope_cached(item_id, request.path))

    def expedient_scope_cached(self, expediente_id, path):
        return self._cached(("image-expedient", str(expediente_id), str(path)), path,
                            lambda: tools.expedient_image_scope(expediente_id, path))

    def expedient_availability(self, identity, request):
        path, expediente_id = identity
        return tools.availability(self.expedient_scope_cached(expediente_id, path))

    # ------------------------------------------------------------------ toolbars

    def inbox_toolbar(self, resolve_item):
        handlers = {
            op: (lambda e, item_id, op=op: self.open(op, lambda: tools.inbox_image_scope(item_id)))
            for op in tools.OPERATIONS
        }
        return InboxImageToolbar(resolve_item, handlers, self.report,
                                 availability=self.inbox_availability)

    def expedient_toolbar(self, expediente_id):
        handlers = {
            op: (lambda e, path, expediente_id, op=op: self.open(
                op, lambda: tools.expedient_image_scope(expediente_id, path)))
            for op in tools.OPERATIONS
        }
        return ExpedientImageToolbar(expediente_id, self.expedient_scope_cached, handlers,
                                     self.report, availability=self.expedient_availability)

    # ------------------------------------------------------------------ forms

    def _form(self, operation, scope):
        reason = tools.availability(scope).get(operation)
        if reason:
            raise ValueError(reason)
        return ImageToolForm(self, operation, scope)

    def open(self, operation, build_scope):
        # A second click before the form shows reuses the open form.
        open_forms = [form for form in self.forms if not form.closed]
        if open_forms:
            return open_forms[-1]
        return super().open(operation, build_scope)
