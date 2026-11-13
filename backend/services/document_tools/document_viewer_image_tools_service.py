"""JPG/JPEG/PNG tools of the document viewer for its two sources: Bandeja items
and documents of an expediente folder.

Same contract as document_viewer_tools_service (PDF): the scope validates
ownership (registered item / expediente folder), real format, size limits and
SHA-256; run_image_tool revalidates the scope, runs one engine of
image_tools_service on the untouched source and registers the derivative in
Bandeja. Crop and image->PDF reuse the existing engines through a temporary
EXIF-oriented working copy. Derivatives live in storage/document_tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services import document_viewer_service
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools import image_tools_service as image_tools
from backend.services.document_tools import safe_file_service
from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.document_viewer_tools_service import ToolScopeError, _sha256
from backend.services.document_tools.safe_file_service import resolve_project_path


OPERATIONS = ("crop", "rotate", "resize", "optimize", "convert", "to_pdf")

# Operation names recorded in Bandeja (crop/to_pdf match the existing inbox routes).
REGISTRY_OPERATIONS = {
    "crop": "image_crop",
    "rotate": "image_rotate",
    "resize": "image_resize",
    "optimize": "image_optimize",
    "convert": "image_convert",
    "to_pdf": "image_to_pdf",
}

# Bandeja states whose file must not be processed.
BLOCKED_INBOX_STATUSES = {"discarded", "duplicate", "error"}


class ImageToolRegistrationError(RuntimeError):
    """The derivative was written but not registered; it is left for review."""

    def __init__(self, message: str, output_paths: list[str]):
        super().__init__(message)
        self.output_paths = list(output_paths)


@dataclass(frozen=True)
class ImageToolScope:
    kind: str  # "inbox" | "expedient"
    source_path: str
    sha256: str
    name: str
    format: str  # "JPEG" | "PNG"
    width: int  # as displayed (EXIF orientation applied)
    height: int
    size_bytes: int
    exif_orientation: int = 1
    has_alpha: bool = False
    inbox_item_id: int | None = None
    expediente_id: int | None = None
    client_id: Any = None
    linked_expedient_id: Any = None
    relative_path: str = ""


def _inspect(source: Path) -> dict:
    if not source.exists() or not source.is_file():
        raise ToolScopeError("El documento no existe.")
    if source.suffix.lower() not in image_tools.EDITABLE_IMAGE_FORMATS:
        raise ToolScopeError("Las herramientas de imagen solo están disponibles para JPG, JPEG o PNG.")
    try:
        img, details = image_tools.open_editable_image(source)
    except Exception as exc:
        raise ToolScopeError(str(exc)) from exc
    img.close()
    return details


def _scope_fields(source: Path, details: dict) -> dict:
    return {
        "source_path": str(source),
        "sha256": _sha256(source),
        "format": details["source_format"],
        "width": details["source_width"],
        "height": details["source_height"],
        "size_bytes": details["source_size_bytes"],
        "exif_orientation": details["exif_orientation"],
        "has_alpha": details["has_alpha"],
    }


# --------------------------------------------------------------------------- scopes

def inbox_image_scope(inbox_item_id: int, path: str | Path | None = None) -> ImageToolScope:
    """Scope of a registered Bandeja image; path, when given, must be that item's file."""
    try:
        item = inbox_tools._get_item_or_fail(int(inbox_item_id))
    except Exception as exc:
        raise ToolScopeError("El documento no está registrado en la Bandeja.") from exc
    if not item or not item.get("stored_path"):
        raise ToolScopeError("El documento no está registrado en la Bandeja.")
    status = str(item.get("status") or "").strip().lower()
    if status in BLOCKED_INBOX_STATUSES:
        raise ToolScopeError(f"El documento está en estado '{status}' en la Bandeja: no se procesa.")

    source = resolve_project_path(item["stored_path"])
    if path is not None and resolve_project_path(path) != source:
        raise ToolScopeError("El documento ya no coincide con el registro de la Bandeja. Vuelve a abrirlo.")
    fields = _scope_fields(source, _inspect(source))

    registered = str(item.get("sha256") or "").strip().lower()
    if registered and registered != fields["sha256"]:
        raise ToolScopeError("El archivo no coincide con la huella SHA-256 registrada en la Bandeja.")

    return ImageToolScope(
        kind="inbox",
        name=str(item.get("original_filename") or source.name),
        inbox_item_id=int(item["id"]),
        client_id=item.get("client_id"),
        linked_expedient_id=item.get("expedient_id"),
        **fields,
    )


def expedient_image_scope(expediente_id: int, path: str | Path) -> ImageToolScope:
    """Scope of a JPG/PNG inside the expediente's document folder (read only)."""
    if not expediente_id:
        raise ToolScopeError("Abre un expediente guardado para usar las herramientas de imagen.")
    try:
        root_info = document_viewer_service.get_expediente_document_root(expediente_id)
    except Exception as exc:
        raise ToolScopeError(f"No se pudo validar la carpeta del expediente: {exc}") from exc
    if not root_info.get("exists"):
        raise ToolScopeError(root_info.get("message") or "La carpeta del expediente no está disponible.")

    root = Path(root_info["root_path"]).expanduser().resolve()
    source = Path(path).expanduser().resolve()
    if not document_viewer_service._is_inside_root(source, root):
        raise ToolScopeError("El archivo no pertenece a la carpeta documental del expediente.")
    fields = _scope_fields(source, _inspect(source))

    return ImageToolScope(
        kind="expedient",
        name=source.name,
        expediente_id=int(expediente_id),
        relative_path=str(source.relative_to(root)),
        **fields,
    )


def rebuild_scope(scope: ImageToolScope) -> ImageToolScope:
    if scope.kind == "inbox":
        return inbox_image_scope(scope.inbox_item_id, scope.source_path)
    return expedient_image_scope(scope.expediente_id, scope.source_path)


def availability(scope: ImageToolScope) -> dict[str, str | None]:
    """operation -> None when enabled, else the real reason it is disabled."""
    return {operation: None for operation in OPERATIONS}


# --------------------------------------------------------------------------- execution

def _coordinate(params: dict, name: str, label: str) -> int:
    try:
        return int(str(params.get(name, "")).strip())
    except ValueError as exc:
        raise ValueError(f"{label}: escribe un número entero de píxeles.") from exc


def _run_engine(operation: str, source: Path, work: Path, params: dict) -> DocumentToolResult:
    stem = source.stem
    if operation == "crop":
        return image_tools.crop_image(
            work, left=_coordinate(params, "left", "Izquierda"), top=_coordinate(params, "top", "Arriba"),
            right=_coordinate(params, "right", "Derecha"), bottom=_coordinate(params, "bottom", "Abajo"),
            output_stem=stem)
    if operation == "rotate":
        return image_tools.rotate_image(source, degrees=params.get("degrees"), output_stem=stem)
    if operation == "resize":
        return image_tools.resize_image(source, width=params.get("width"), height=params.get("height"),
                                        output_stem=stem)
    if operation == "optimize":
        return image_tools.optimize_image(source, quality=params.get("quality"), output_stem=stem)
    if operation == "convert":
        return image_tools.convert_image_format(source, target_format=params.get("target_format"),
                                                output_stem=stem)
    return image_tools.image_to_pdf(work, output_stem=stem)


def run_image_tool(scope: ImageToolScope, operation: str, params: dict | None = None) -> dict[str, Any]:
    """Run one image tool and register its derivative in Bandeja.

    Raises ValueError with a user-facing message when nothing was produced.
    If the derivative was written but could not be registered, raises
    ImageToolRegistrationError naming the derivative left for review.
    """
    if operation not in OPERATIONS:
        raise ValueError(f"Operación no soportada: {operation}")
    params = dict(params or {})

    current = rebuild_scope(scope)
    if current.sha256 != scope.sha256:
        raise ValueError("El documento ha cambiado desde que se abrió el formulario. Vuelve a abrirlo.")
    source = Path(current.source_path)

    work = None
    try:
        if operation in ("crop", "to_pdf"):
            work = image_tools.oriented_working_copy(source, flatten_alpha=operation == "to_pdf")
        result = _run_engine(operation, source, work or source, params)
    finally:
        if work is not None:
            Path(work).unlink(missing_ok=True)

    if not result.ok:
        errors = [str(x) for x in result.errors + result.warnings]
        raise ValueError(" | ".join(errors[:2]) or "La operación no se pudo completar.")

    output = Path(result.output_path).resolve()
    if _sha256(source) != current.sha256:
        raise RuntimeError("La imagen original ha cambiado durante la operación; revisa el documento. "
                           f"Derivado pendiente de revisión: {output}")
    tools_root = Path(safe_file_service.DOCUMENT_TOOLS_ROOT).resolve()
    if output == source.resolve() or not output.is_relative_to(tools_root):
        raise RuntimeError(f"El derivado no está en storage/document_tools; no se registra: {output}")

    if work is not None:
        result = _with_original_source(result, current, operation)

    try:
        response = _register(current, operation, result)
    except Exception as exc:
        raise ImageToolRegistrationError(
            f"La copia se generó pero no se pudo registrar en la Bandeja: {exc}. "
            f"Derivado pendiente de revisión: {output}",
            [str(output)],
        ) from exc

    return {
        "ok": True,
        "operation": operation,
        "scope": current.kind,
        "source_path": current.source_path,
        "source_sha256": current.sha256,
        "outputs": [str(output)],
        "generated_items": [response["generated_item"]],
        "response": response,
    }


def _with_original_source(result: DocumentToolResult, scope: ImageToolScope, operation: str) -> DocumentToolResult:
    """The engine read a temporary working copy; record the real source instead."""
    flattened = operation == "to_pdf" and scope.has_alpha
    metadata = dict(result.metadata)
    metadata.update({
        "exif_orientation": scope.exif_orientation,
        "exif_orientation_applied": scope.exif_orientation != 1,
        "alpha_flattened": flattened,
        "background": image_tools.JPEG_BACKGROUND_HEX if flattened else None,
    })
    return DocumentToolResult.success(
        operation=result.operation, source_paths=[scope.source_path], output_path=result.output_path,
        warnings=result.warnings, metadata=metadata)


def _register(scope: ImageToolScope, operation: str, result: DocumentToolResult) -> dict:
    registry_operation = REGISTRY_OPERATIONS[operation]
    if scope.kind == "inbox":
        item = inbox_tools._get_item_or_fail(scope.inbox_item_id)
        response = inbox_tools._build_operation_response(
            source_items=[item], result=result, register_result=True, operation=registry_operation)
    else:
        provenance = {
            "source_context": "expedient",
            "expediente_id": scope.expediente_id,
            "source_relative_path": scope.relative_path,
            "source_sha256": scope.sha256,
        }
        response = {
            "ok": True,
            "operation": registry_operation,
            "result": result.to_dict(),
            "generated_item": inbox_tools.register_generated_document(
                result, operation=registry_operation, expedient_id=scope.expediente_id,
                provenance=provenance),
        }
    if not isinstance(response.get("generated_item"), dict):
        raise RuntimeError("el registro no devolvió el nuevo documento")
    return response
