"""JPG/JPEG/PNG tools of the document viewer for its two sources: Bandeja items
and documents of an expediente folder.

Same contract as document_viewer_tools_service (PDF): the scope validates
ownership (registered item / expediente folder), real format, size limits and
SHA-256; run_image_tool revalidates the scope, runs one engine of
image_tools_service on the untouched source and registers the derivative in
Bandeja. Crop and image->PDF reuse the existing engines through a temporary
EXIF-oriented working copy. Derivatives live in storage/document_tools.

DV29-WO-03: several JPG/PNG of the viewer selection -> one multipage PDF.
images_scope validates every source like the single tools (same Bandeja
link, or the same expediente folder), run_images_to_pdf revalidates them,
writes one page per source in the confirmed order through
image_tools_service.images_to_pdf and registers one derivative whose
metadata lists every source and its page.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services import document_viewer_service
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools import image_tools_service as image_tools
from backend.services.document_tools import pdf_tools_service as pdf_tools
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


# --------------------------------------------------------------------------- several images -> one PDF

MULTI_OPERATION = "images_to_pdf"
MIN_PDF_SOURCES = 2
MAX_PDF_SOURCES = 30

# Reviews already executed (or running): a replayed confirmation never writes twice.
_SPENT_REVIEWS: set[str] = set()
_SPENT_LOCK = threading.Lock()


@dataclass(frozen=True)
class ImagesToPdfScope:
    kind: str  # "inbox" | "expedient"
    sources: tuple  # ImageToolScope, in the order the viewer selection lists them
    expediente_id: int | None = None
    client_id: Any = None
    linked_expedient_id: Any = None
    # One review = one confirmation; see run_images_to_pdf.
    token: str = field(default_factory=lambda: uuid4().hex)

    @property
    def page_count(self) -> int:
        return len(self.sources)


def _path_key(path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _source_label(scope: ImageToolScope) -> str:
    if scope.kind == "inbox":
        return f"{scope.name} (Bandeja #{scope.inbox_item_id})"
    return scope.relative_path or scope.name


def _check_count(count: int) -> None:
    if count < MIN_PDF_SOURCES:
        raise ToolScopeError(f"Selecciona al menos {MIN_PDF_SOURCES} imágenes JPG o PNG para unirlas en un PDF.")
    if count > MAX_PDF_SOURCES:
        raise ToolScopeError(f"Demasiadas imágenes: máximo {MAX_PDF_SOURCES} por PDF.")


def _check_distinct(sources: tuple) -> None:
    """Same file or same content twice is a duplicate; homonyms are fine."""
    seen_paths, seen_hashes = {}, {}
    for source in sources:
        for seen, key in ((seen_paths, _path_key(source.source_path)), (seen_hashes, source.sha256)):
            if key in seen:
                raise ToolScopeError(f"Imagen duplicada en la selección: {_source_label(seen[key])} y "
                                     f"{_source_label(source)}.")
            seen[key] = source


def _link_value(value):
    return None if value in (None, "", 0, "0") else str(value)


def inbox_images_scope(inbox_item_ids, paths=None) -> ImagesToPdfScope:
    """Registered Bandeja images with the same client/expediente link.

    ``paths``, when given, must be the registered file of each item.
    """
    ids = list(inbox_item_ids or ())
    _check_count(len(ids))
    paths = list(paths) if paths is not None else [None] * len(ids)
    if len(paths) != len(ids):
        raise ToolScopeError("La selección no coincide con los documentos revisados. Vuelve a abrirla.")
    try:
        ids = [int(item_id) for item_id in ids]
    except (TypeError, ValueError) as exc:
        raise ToolScopeError("La selección incluye un documento que no es de la Bandeja.") from exc
    if len(set(ids)) != len(ids):
        raise ToolScopeError("La selección repite un documento de la Bandeja.")

    sources = []
    for item_id, path in zip(ids, paths):
        try:
            sources.append(inbox_image_scope(item_id, path))
        except ToolScopeError as exc:
            raise ToolScopeError(f"Bandeja #{item_id}: {exc}") from exc
    sources = tuple(sources)
    _check_distinct(sources)

    links = {(_link_value(s.client_id), _link_value(s.linked_expedient_id)) for s in sources}
    if len(links) != 1:
        raise ToolScopeError("Las imágenes no tienen la misma vinculación de cliente y expediente en la "
                             "Bandeja: no se mezclan contextos en un mismo PDF.")
    return ImagesToPdfScope(kind="inbox", sources=sources, client_id=sources[0].client_id,
                            linked_expedient_id=sources[0].linked_expedient_id)


def expedient_images_scope(expediente_id: int, paths) -> ImagesToPdfScope:
    """JPG/PNG inside the document folder of one expediente (read only)."""
    paths = list(paths or ())
    _check_count(len(paths))
    sources = []
    for path in paths:
        try:
            sources.append(expedient_image_scope(expediente_id, path))
        except ToolScopeError as exc:
            raise ToolScopeError(f"{Path(str(path or '')).name or 'Documento'}: {exc}") from exc
    sources = tuple(sources)
    _check_distinct(sources)
    return ImagesToPdfScope(kind="expedient", sources=sources, expediente_id=int(expediente_id))


def rebuild_images_scope(scope: ImagesToPdfScope) -> ImagesToPdfScope:
    if scope.kind == "inbox":
        return inbox_images_scope([s.inbox_item_id for s in scope.sources],
                                  [s.source_path for s in scope.sources])
    return expedient_images_scope(scope.expediente_id, [s.source_path for s in scope.sources])


def _confirmed_order(scope: ImagesToPdfScope, order) -> list[int]:
    count = scope.page_count
    if order is None:
        return list(range(count))
    try:
        indexes = [int(index) for index in order]
    except (TypeError, ValueError) as exc:
        raise ValueError("El orden confirmado no es válido.") from exc
    if sorted(indexes) != list(range(count)):
        raise ValueError("El orden confirmado no corresponde a las imágenes revisadas.")
    return indexes


def _claim(token: str) -> None:
    with _SPENT_LOCK:
        if not token or token in _SPENT_REVIEWS:
            raise ValueError("Esta revisión ya se confirmó: no se genera otra copia. "
                             "Vuelve a abrir la herramienta para crear otro PDF.")
        _SPENT_REVIEWS.add(token)


def _release(token: str) -> None:
    with _SPENT_LOCK:
        _SPENT_REVIEWS.discard(token)


def review_spent(token: str) -> bool:
    """True once a review has run (or is running) and cannot be confirmed again."""
    with _SPENT_LOCK:
        return token in _SPENT_REVIEWS


def _write_pdf(ordered: list[ImageToolScope]) -> DocumentToolResult:
    """One page per source, each EXIF-oriented and with alpha flattened on white."""
    works = []
    try:
        for source in ordered:
            works.append(image_tools.oriented_working_copy(source.source_path, flatten_alpha=True))
        inputs = [work or source.source_path for work, source in zip(works, ordered)]
        stem = f"{Path(ordered[0].source_path).stem}_{len(ordered)}_imagenes"
        return image_tools.images_to_pdf(inputs, output_stem=stem)
    finally:
        for work in works:
            if work is not None:
                Path(work).unlink(missing_ok=True)


def _page_trace(ordered: list[ImageToolScope]) -> list[dict]:
    pages = []
    for number, source in enumerate(ordered, start=1):
        entry = {
            "page": number,
            "name": source.name,
            "source_path": source.source_path,
            "source_sha256": source.sha256,
            "source_format": source.format,
            "width": source.width,
            "height": source.height,
            "exif_orientation_applied": source.exif_orientation != 1,
            "alpha_flattened": source.has_alpha,
        }
        if source.kind == "inbox":
            entry["inbox_item_id"] = source.inbox_item_id
        else:
            entry["source_relative_path"] = source.relative_path
        pages.append(entry)
    return pages


def run_images_to_pdf(scope: ImagesToPdfScope, order=None) -> dict[str, Any]:
    """Join the reviewed images into one new PDF and register it once in Bandeja.

    ``order``: indexes of scope.sources in the confirmed page order. A scope
    (one review) runs at most once; a failure before anything is written
    releases it for a retry. Raises ValueError when nothing was produced and
    ImageToolRegistrationError when the PDF exists but is not registered.
    """
    if not isinstance(scope, ImagesToPdfScope):
        raise ValueError("Revisión de imágenes no válida.")
    indexes = _confirmed_order(scope, order)
    _claim(scope.token)
    try:
        current = rebuild_images_scope(scope)
        if current.kind != scope.kind or [s.sha256 for s in current.sources] != [s.sha256 for s in scope.sources]:
            raise ValueError("Alguna imagen ha cambiado desde la revisión. Vuelve a abrir la herramienta.")
        ordered = [current.sources[index] for index in indexes]
        result = _write_pdf(ordered)
        if not result.ok:
            errors = [str(x) for x in result.errors + result.warnings]
            raise ValueError(" | ".join(errors[:2]) or "No se pudo generar el PDF.")
    except Exception:
        _release(scope.token)
        raise

    # From here a file exists: this review is spent whatever happens next.
    output = Path(result.output_path).resolve()
    tools_root = Path(safe_file_service.DOCUMENT_TOOLS_ROOT).resolve()
    if not output.is_relative_to(tools_root) or any(output == Path(s.source_path).resolve() for s in ordered):
        raise RuntimeError(f"El PDF no está en storage/document_tools; no se registra: {output}")
    if any(_sha256(Path(s.source_path)) != s.sha256 for s in ordered):
        raise RuntimeError("Alguna imagen original ha cambiado durante la operación; revisa los documentos. "
                           f"PDF pendiente de revisión (no registrado): {output}")
    if pdf_tools.PdfReader is not None:
        try:
            pages = len(pdf_tools.PdfReader(str(output)).pages)
        except Exception as exc:
            raise RuntimeError(f"El PDF generado no se puede leer ({exc}); no se registra. "
                               f"PDF pendiente de revisión: {output}") from exc
        if pages != len(ordered):
            raise RuntimeError(f"El PDF tiene {pages} página(s) y se esperaban {len(ordered)}; no se registra. "
                               f"PDF pendiente de revisión: {output}")

    metadata = dict(result.metadata)
    metadata.update({
        "page_count": len(ordered),
        "pages": _page_trace(ordered),
        "background": image_tools.JPEG_BACKGROUND_HEX if any(s.has_alpha for s in ordered) else None,
        "review_token": scope.token,
    })
    result = DocumentToolResult.success(
        operation=result.operation, source_paths=[s.source_path for s in ordered],
        output_path=result.output_path, warnings=result.warnings, metadata=metadata)

    try:
        response = _register_many(current, ordered, result)
    except Exception as exc:
        raise ImageToolRegistrationError(
            f"El PDF se generó pero no se pudo registrar en la Bandeja: {exc}. "
            f"PDF no registrado, pendiente de revisión: {output}",
            [str(output)],
        ) from exc

    return {
        "ok": True,
        "operation": MULTI_OPERATION,
        "scope": current.kind,
        "source_paths": [s.source_path for s in ordered],
        "source_sha256": [s.sha256 for s in ordered],
        "page_count": len(ordered),
        "outputs": [str(output)],
        "generated_items": [response["generated_item"]],
        "response": response,
    }


def _register_many(scope: ImagesToPdfScope, ordered: list[ImageToolScope], result: DocumentToolResult) -> dict:
    """One Bandeja item for the PDF; its metadata names every source in page order."""
    if scope.kind == "inbox":
        items = [inbox_tools._get_item_or_fail(source.inbox_item_id) for source in ordered]
        response = inbox_tools._build_operation_response(
            source_items=items, result=result, register_result=True, operation=MULTI_OPERATION)
    else:
        provenance = {
            "source_context": "expedient",
            "expediente_id": scope.expediente_id,
            "sources": [{"page": page["page"], "source_relative_path": page["source_relative_path"],
                         "source_sha256": page["source_sha256"]} for page in _page_trace(ordered)],
        }
        response = {
            "ok": True,
            "operation": MULTI_OPERATION,
            "result": result.to_dict(),
            "generated_item": inbox_tools.register_generated_document(
                result, operation=MULTI_OPERATION, expedient_id=scope.expediente_id,
                provenance=provenance),
        }
    if not isinstance(response.get("generated_item"), dict):
        raise RuntimeError("el registro no devolvió el nuevo documento")
    return response
