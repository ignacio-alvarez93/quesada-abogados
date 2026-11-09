"""PDF tools of the document viewer for its two sources: Bandeja items and
documents of an expediente folder.

Validates scope (registered item / folder ownership), reuses the existing
engines of pdf_tools_service and the Bandeja flows of
document_inbox_tools_service, and registers every derivative in Bandeja.
The source PDF is never written; derivatives live in storage/document_tools.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.services import document_viewer_service
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools import pdf_tools_service as pdf_tools
from backend.services.document_tools.safe_file_service import resolve_project_path


OPERATIONS = ("rotate", "move_page", "split", "compress", "extract", "merge", "annotate")

# Operations that make no sense on a single-page PDF.
MULTIPAGE_ONLY = {
    "move_page": "El PDF tiene una sola página: no hay nada que mover.",
    "split": "El PDF tiene una sola página: no se puede dividir.",
    "extract": "El PDF tiene una sola página: extraer equivaldría a copiarlo.",
}


class ToolScopeError(ValueError):
    """The document cannot be processed in this context; message is user-facing."""


@dataclass(frozen=True)
class ToolScope:
    kind: str  # "inbox" | "expedient"
    source_path: str
    sha256: str
    page_count: int
    name: str
    inbox_item_id: int | None = None
    expediente_id: int | None = None
    client_id: Any = None
    linked_expedient_id: Any = None
    relative_path: str = ""
    merge_candidates: tuple = field(default=(), compare=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_page_count(path: Path) -> int:
    if pdf_tools.PdfReader is None or pdf_tools.PdfWriter is None:
        raise ToolScopeError("Falta la dependencia pypdf; las herramientas PDF no están disponibles.")
    try:
        reader = pdf_tools.PdfReader(str(path))
        if reader.is_encrypted:
            raise ToolScopeError("PDF cifrado: no se puede procesar.")
        return len(reader.pages)
    except ToolScopeError:
        raise
    except Exception as exc:
        raise ToolScopeError(f"El PDF no se puede leer: {exc}") from exc


def _require_pdf_file(path: Path) -> None:
    if path.suffix.lower() != ".pdf":
        raise ToolScopeError("Las herramientas PDF solo están disponibles para documentos PDF.")
    if not path.exists() or not path.is_file():
        raise ToolScopeError("El documento no existe.")


def _same_link(item: dict, scope_client, scope_expedient) -> bool:
    def norm(value):
        return None if value in (None, "", 0) else str(value)
    return norm(item.get("client_id")) == norm(scope_client) and norm(item.get("expedient_id")) == norm(scope_expedient)


# --------------------------------------------------------------------------- scopes

def inbox_scope(inbox_item_id: int, path: str | Path | None = None, *, inbox_items=()) -> ToolScope:
    """Scope of a registered Bandeja item; path, when given, must be that item's file.

    inbox_items: items visible in Bandeja; merge candidates are the PDFs among
    them linked to the same client and expediente as this item.
    """
    try:
        item = inbox_tools._get_item_or_fail(int(inbox_item_id))
    except Exception as exc:
        raise ToolScopeError("El documento no está registrado en la Bandeja.") from exc
    if not item or not item.get("stored_path"):
        raise ToolScopeError("El documento no está registrado en la Bandeja.")

    source = resolve_project_path(item["stored_path"])
    if path is not None and resolve_project_path(path) != source:
        raise ToolScopeError("El documento ya no coincide con el registro de la Bandeja. Vuelve a abrirlo.")
    _require_pdf_file(source)
    page_count = _pdf_page_count(source)

    candidates = []
    for other in inbox_items or ():
        candidate = _inbox_candidate(other, item, source)
        if candidate:
            candidates.append(candidate)

    return ToolScope(
        kind="inbox",
        source_path=str(source),
        sha256=_sha256(source),
        page_count=page_count,
        name=str(item.get("original_filename") or source.name),
        inbox_item_id=int(item["id"]),
        client_id=item.get("client_id"),
        linked_expedient_id=item.get("expedient_id"),
        merge_candidates=tuple(candidates),
    )


def _inbox_candidate(other: dict, item: dict, source: Path) -> dict | None:
    try:
        other_id = int(other.get("id"))
    except Exception:
        return None
    if other_id == int(item["id"]) or not other.get("stored_path"):
        return None
    if not _same_link(other, item.get("client_id"), item.get("expedient_id")):
        return None
    path = resolve_project_path(other["stored_path"])
    if path == source or path.suffix.lower() != ".pdf" or not path.is_file():
        return None
    return {"key": f"inbox:{other_id}", "item_id": other_id, "path": str(path),
            "name": str(other.get("original_filename") or path.name)}


def expedient_scope(expediente_id: int, path: str | Path) -> ToolScope:
    """Scope of a PDF inside the expediente's document folder (read only)."""
    if not expediente_id:
        raise ToolScopeError("Abre un expediente guardado para usar las herramientas PDF.")
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
    _require_pdf_file(source)
    page_count = _pdf_page_count(source)

    return ToolScope(
        kind="expedient",
        source_path=str(source),
        sha256=_sha256(source),
        page_count=page_count,
        name=source.name,
        expediente_id=int(expediente_id),
        relative_path=str(source.relative_to(root)),
        merge_candidates=tuple(_expedient_candidates(expediente_id, root, source)),
    )


def _expedient_candidates(expediente_id, root: Path, source: Path) -> list[dict]:
    try:
        listing = document_viewer_service.list_expediente_documents(expediente_id)
    except Exception:
        return []
    candidates = []
    for doc in listing.get("documents") or []:
        raw = doc.get("path")
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if (path == source or path.suffix.lower() != ".pdf" or not path.is_file()
                or not document_viewer_service._is_inside_root(path, root)):
            continue
        candidates.append({"key": f"expedient:{path.relative_to(root)}", "path": str(path),
                           "name": str(doc.get("relative_path") or path.name)})
    return candidates


def rebuild_scope(scope: ToolScope, *, inbox_items=()) -> ToolScope:
    if scope.kind == "inbox":
        return inbox_scope(scope.inbox_item_id, scope.source_path, inbox_items=inbox_items)
    return expedient_scope(scope.expediente_id, scope.source_path)


def availability(scope: ToolScope) -> dict[str, str | None]:
    """operation -> None when enabled, else the real reason it is disabled."""
    reasons = {}
    for operation in OPERATIONS:
        reason = None
        if operation in MULTIPAGE_ONLY and scope.page_count < 2:
            reason = MULTIPAGE_ONLY[operation]
        elif operation == "merge" and not scope.merge_candidates:
            reason = ("No hay otros PDF de la misma carpeta del expediente para unir."
                      if scope.kind == "expedient" else
                      "No hay otros PDF en la Bandeja vinculados al mismo cliente/expediente para unir.")
        reasons[operation] = reason
    return reasons


# --------------------------------------------------------------------------- parameters

def parse_page_list(raw: str, page_count: int) -> list[int]:
    """'1,3,5-8' -> [1, 3, 5, 6, 7, 8] (order kept, duplicates removed)."""
    try:
        return pdf_tools._parse_page_ranges_for_pdf_tools(str(raw or ""), page_count)
    except ValueError as exc:
        if "invalid literal" in str(exc):
            raise ValueError("Formato de páginas no válido. Ejemplo: 1,3,5-8") from exc
        raise


def parse_split_ranges(raw: str, page_count: int) -> list[tuple[int, int]]:
    """'1-2,3-5,6' -> [(1, 2), (3, 5), (6, 6)]."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Indica los rangos. Ejemplo: 1-2,3-5")
    ranges = []
    try:
        for chunk in text.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            start, _, end = chunk.partition("-")
            first, last = int(start), int(end or start)
            ranges.append((first, last))
    except ValueError as exc:
        raise ValueError("Formato de rangos no válido. Ejemplo: 1-2,3-5") from exc
    if not ranges:
        raise ValueError("Indica al menos un rango.")
    for first, last in ranges:
        if first < 1 or first > last or last > page_count:
            raise ValueError(f"Rango fuera de límites: {first}-{last}. El PDF tiene {page_count} páginas.")
    return ranges


def _int_param(params, name, label):
    try:
        return int(str(params.get(name, "")).strip())
    except ValueError as exc:
        raise ValueError(f"{label}: escribe un número de página.") from exc


# --------------------------------------------------------------------------- execution

def run_tool(scope: ToolScope, operation: str, params: dict | None = None, *, inbox_items=()) -> dict[str, Any]:
    """Run one viewer tool and register its derivative(s) in Bandeja.

    Raises ValueError with a user-facing message on any failure. The source is
    revalidated first (an edited, moved or re-registered file is refused) and
    verified byte-identical afterwards.
    """
    if operation not in OPERATIONS:
        raise ValueError(f"Operación no soportada: {operation}")
    params = dict(params or {})

    current = rebuild_scope(scope, inbox_items=inbox_items)
    if current.sha256 != scope.sha256:
        raise ValueError("El documento ha cambiado desde que se abrió el formulario. Vuelve a abrirlo.")
    reason = availability(current).get(operation)
    if reason:
        raise ValueError(reason)

    if current.kind == "inbox":
        response = _run_inbox(current, operation, params)
    else:
        response = _run_expedient(current, operation, params)

    if _sha256(Path(current.source_path)) != current.sha256:
        raise RuntimeError("El PDF original ha cambiado durante la operación; revisa el documento.")

    result = response.get("result") or {}
    if not response.get("ok"):
        errors = [str(x) for x in (result.get("errors") or []) + (result.get("warnings") or [])]
        raise ValueError(" | ".join(errors[:2]) or "La operación no se pudo completar.")

    generated = [x for x in [response.get("generated_item")] + list(response.get("generated_items") or [])
                 if isinstance(x, dict)]
    outputs = [o.get("output_path") for o in (result.get("metadata") or {}).get("outputs") or []] \
        or [result.get("output_path")]
    return {
        "ok": True,
        "operation": operation,
        "scope": current.kind,
        "source_path": current.source_path,
        "outputs": [str(x) for x in outputs if x],
        "generated_items": generated,
        "response": response,
    }


def _merge_paths(scope: ToolScope, params: dict) -> list[dict]:
    """Ordered sources from params['order']: 'current' and candidate keys only."""
    order = list(params.get("order") or [])
    if len(order) != len(set(order)):
        raise ValueError("Un PDF aparece repetido en el orden de unión.")
    if len(order) < 2:
        raise ValueError("Selecciona al menos otro PDF para unir.")
    allowed = {c["key"]: c for c in scope.merge_candidates}
    current = {"key": "current", "path": scope.source_path, "item_id": scope.inbox_item_id}
    chosen = []
    for key in order:
        if key == "current":
            chosen.append(current)
        elif key in allowed:
            chosen.append(allowed[key])
        else:
            raise ValueError("Uno de los PDF elegidos ya no está disponible en este contexto.")
    return chosen


def _run_inbox(scope: ToolScope, operation: str, params: dict) -> dict:
    item_id = scope.inbox_item_id
    if operation == "rotate":
        pages = parse_page_list(params.get("pages"), scope.page_count)
        return inbox_tools.rotate_pages_in_inbox_pdf(
            item_id, page_ranges=pages, degrees=int(params.get("degrees") or 90),
            output_stem="pdf_paginas_rotadas_bandeja")
    if operation == "move_page":
        return inbox_tools.move_page_in_inbox_pdf(
            item_id, page_number=_int_param(params, "page_number", "Página a mover"),
            target_position=_int_param(params, "target_position", "Nueva posición"),
            output_stem="pdf_pagina_movida_bandeja")
    if operation == "split":
        return inbox_tools.split_inbox_pdf_by_ranges(
            item_id, ranges=parse_split_ranges(params.get("ranges"), scope.page_count),
            output_stem="pdf_dividido_bandeja")
    if operation == "compress":
        return inbox_tools.compress_inbox_pdf_smart(item_id, output_stem="pdf_comprimido_bandeja")
    if operation == "extract":
        return inbox_tools.extract_pages_from_inbox_pdf(
            item_id, pages=parse_page_list(params.get("pages"), scope.page_count),
            output_stem="pdf_paginas_extraidas_bandeja")
    if operation == "merge":
        ids = [c.get("item_id") or item_id for c in _merge_paths(scope, params)]
        return inbox_tools.merge_inbox_pdfs(ids, output_stem="pdf_unido_bandeja")
    return inbox_tools.annotate_inbox_pdf(
        item_id, page_number=_int_param(params, "page_number", "Página"),
        text=params.get("text") or "", position=params.get("position") or "top",
        output_stem="pdf_anotado_bandeja")


def _run_expedient(scope: ToolScope, operation: str, params: dict) -> dict:
    source = scope.source_path
    if operation == "rotate":
        result = pdf_tools.rotate_pdf_pages(
            source, page_ranges=parse_page_list(params.get("pages"), scope.page_count),
            degrees=int(params.get("degrees") or 90))
    elif operation == "move_page":
        result = pdf_tools.move_pdf_page(
            source, page_number=_int_param(params, "page_number", "Página a mover"),
            target_position=_int_param(params, "target_position", "Nueva posición"))
    elif operation == "split":
        result = pdf_tools.split_pdf_by_ranges(
            source, ranges=parse_split_ranges(params.get("ranges"), scope.page_count))
    elif operation == "compress":
        result = pdf_tools.compress_pdf_smart(source)
    elif operation == "extract":
        result = pdf_tools.extract_pdf_pages(
            source, pages=parse_page_list(params.get("pages"), scope.page_count))
    elif operation == "merge":
        result = pdf_tools.merge_pdfs([c["path"] for c in _merge_paths(scope, params)],
                                      output_stem=f"{Path(source).stem}_unido")
    else:
        result = pdf_tools.annotate_pdf_text(
            source, page_number=_int_param(params, "page_number", "Página"),
            text=params.get("text") or "", position=params.get("position") or "top")

    response = {"ok": result.ok, "operation": result.operation, "result": result.to_dict(),
                "generated_items": []}
    if not result.ok:
        return response

    provenance = {
        "source_context": "expedient",
        "expediente_id": scope.expediente_id,
        "source_relative_path": scope.relative_path,
        "source_sha256": scope.sha256,
    }
    outputs = result.metadata.get("outputs") or [{"output_path": result.output_path}]
    for output in outputs:
        single = result if len(outputs) == 1 else pdf_tools.DocumentToolResult.success(
            operation=result.operation, source_paths=result.source_paths,
            output_path=output["output_path"],
            metadata={"range": output.get("range"), "page_count": output.get("page_count"),
                      "parent_result": result.to_dict()})
        response["generated_items"].append(inbox_tools.register_generated_document(
            single, operation=result.operation, expedient_id=scope.expediente_id,
            provenance=provenance))
    return response
