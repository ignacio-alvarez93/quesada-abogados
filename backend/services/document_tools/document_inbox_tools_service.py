from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from backend.services.document_inbox_service import (
    get_inbox_item,
    import_file_to_inbox,
)
from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.document_metadata_service import get_document_metadata
from backend.services.document_tools.image_tools_service import (
    image_to_pdf,
    images_to_pdf,
)
from backend.services.document_tools.pdf_tools_service import (
    extract_pdf_pages,
    merge_pdfs,
    remove_pdf_pages,
)
from backend.services.document_tools.safe_file_service import assert_existing_file, resolve_project_path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def get_inbox_item_document_metadata(inbox_item_id: int) -> dict[str, Any]:
    """
    Devuelve metadatos técnicos de un item de la Bandeja Documental.

    No genera archivo nuevo.
    No modifica el item original.
    """
    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = get_document_metadata(source_path)

    return {
        "item": item,
        "result": result.to_dict(),
    }


def convert_inbox_image_to_pdf(
    inbox_item_id: int,
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    """
    Convierte una imagen de Bandeja Documental a PDF.

    Si register_result=True, importa el PDF generado como nuevo item de Bandeja.
    """
    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = image_to_pdf(source_path, output_stem=output_stem)

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="image_to_pdf",
    )


def convert_inbox_images_to_pdf(
    inbox_item_ids: list[int],
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    """
    Convierte varias imágenes de Bandeja Documental a un único PDF multipágina.
    """
    items = [_get_item_or_fail(item_id) for item_id in inbox_item_ids]
    source_paths = [_resolve_inbox_item_path(item) for item in items]

    result = images_to_pdf(source_paths, output_stem=output_stem)

    return _build_operation_response(
        source_items=items,
        result=result,
        register_result=register_result,
        operation="images_to_pdf",
    )


def merge_inbox_pdfs(
    inbox_item_ids: list[int],
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    """
    Une varios PDFs de Bandeja Documental generando un nuevo PDF.
    """
    items = [_get_item_or_fail(item_id) for item_id in inbox_item_ids]
    source_paths = [_resolve_inbox_item_path(item) for item in items]

    result = merge_pdfs(source_paths, output_stem=output_stem)

    return _build_operation_response(
        source_items=items,
        result=result,
        register_result=register_result,
        operation="pdf_merge",
    )


def extract_pages_from_inbox_pdf(
    inbox_item_id: int,
    pages: list[int],
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    """
    Extrae páginas de un PDF de Bandeja Documental.

    pages usa numeración humana: [1, 2, 5].
    """
    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = extract_pdf_pages(source_path, pages=pages, output_stem=output_stem)

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="pdf_extract_pages",
    )


def remove_pages_from_inbox_pdf(
    inbox_item_id: int,
    pages_to_remove: list[int],
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    """
    Elimina páginas de un PDF de Bandeja Documental generando copia nueva.

    pages_to_remove usa numeración humana: [1, 3].
    """
    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = remove_pdf_pages(
        source_path,
        pages_to_remove=pages_to_remove,
        output_stem=output_stem,
    )

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="pdf_remove_pages",
    )


def _get_item_or_fail(inbox_item_id: int) -> dict[str, Any]:
    item = get_inbox_item(int(inbox_item_id))

    if not item:
        raise ValueError(f"No existe el item de Bandeja Documental: {inbox_item_id}")

    return item


def _resolve_inbox_item_path(item: dict[str, Any]) -> Path:
    """
    Resuelve la ruta física del documento.

    Se hace defensivo porque el modelo ha ido creciendo y pueden existir nombres
    de campo distintos según importación/manual/Box.
    """
    path_candidates = [
        item.get("stored_path"),
        item.get("file_path"),
        item.get("local_path"),
        item.get("path"),
        item.get("original_path"),
    ]

    metadata = _metadata_dict(item.get("metadata_json"))
    path_candidates.extend(
        [
            metadata.get("stored_path"),
            metadata.get("file_path"),
            metadata.get("local_path"),
            metadata.get("original_path"),
            metadata.get("source_path"),
        ]
    )

    for candidate in path_candidates:
        if not candidate:
            continue

        try:
            resolved = resolve_project_path(candidate)
            return assert_existing_file(resolved)
        except Exception:
            continue

    raise FileNotFoundError(
        "No se pudo resolver la ruta física del item de Bandeja Documental "
        f"id={item.get('id')}. Campos disponibles: {sorted(item.keys())}"
    )


def _build_operation_response(
    *,
    source_items: list[dict[str, Any]],
    result: DocumentToolResult,
    register_result: bool,
    operation: str,
) -> dict[str, Any]:
    generated_item = None

    if result.ok and register_result and result.output_path:
        generated_item = _register_generated_result(
            source_items=source_items,
            result=result,
            operation=operation,
        )

    return {
        "ok": result.ok,
        "operation": operation,
        "source_item_ids": [item.get("id") for item in source_items],
        "result": result.to_dict(),
        "generated_item": generated_item,
    }


def _register_generated_result(
    *,
    source_items: list[dict[str, Any]],
    result: DocumentToolResult,
    operation: str,
) -> dict[str, Any]:
    if not result.output_path:
        raise ValueError("No hay archivo generado para registrar en Bandeja Documental.")

    first_item = source_items[0] if source_items else {}

    client_id = _first_non_empty([item.get("client_id") for item in source_items])
    expedient_id = _first_non_empty([item.get("expedient_id") for item in source_items])

    metadata = {
        "generated_by": "document_tools",
        "operation": operation,
        "source_item_ids": [item.get("id") for item in source_items],
        "source_paths": result.source_paths,
        "tool_result": result.to_dict(),
    }

    notes = (
        f"Generado automáticamente por herramientas documentales "
        f"desde item(s): {', '.join(str(x.get('id')) for x in source_items)}"
    )

    kwargs = {
        # Firma real actual de document_inbox_service.import_file_to_inbox.
        "file_path": result.output_path,

        # Alias defensivos para futuras evoluciones del servicio.
        "source_path": result.output_path,

        "source_type": "generated",
        "source_label": f"document_tools:{operation}",
        "client_id": client_id,
        "expedient_id": expedient_id,
        "notes": notes,
        "metadata_json": metadata,
    }

    # Compatibilidad defensiva con la firma real de import_file_to_inbox.
    # Si el servicio evoluciona, solo pasamos parámetros existentes.
    imported = _call_with_supported_kwargs(import_file_to_inbox, kwargs)

    if not isinstance(imported, dict):
        return {
            "raw": imported,
            "source_type": "generated",
            "operation": operation,
            "output_path": result.output_path,
        }

    return imported


def _call_with_supported_kwargs(func, kwargs: dict[str, Any]):
    signature = inspect.signature(func)
    accepted = {}

    for name, param in signature.parameters.items():
        if name in kwargs:
            accepted[name] = kwargs[name]

    return func(**accepted)


def _metadata_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    return {}


def _first_non_empty(values):
    for value in values:
        if value not in (None, "", 0):
            return value
    return None

def reorder_pages_from_inbox_pdf(
    inbox_item_id: int,
    ordered_pages: list[int],
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.pdf_tools_service import reorder_pdf_pages

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = reorder_pdf_pages(
        source_path,
        ordered_pages=ordered_pages,
        output_stem=output_stem,
    )

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="pdf_reorder_pages",
    )


def split_inbox_pdf_by_ranges(
    inbox_item_id: int,
    ranges: list[tuple[int, int]],
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.pdf_tools_service import split_pdf_by_ranges

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = split_pdf_by_ranges(
        source_path,
        ranges=ranges,
        output_stem=output_stem,
    )

    generated_items = []

    if result.ok and register_result:
        outputs = result.metadata.get("outputs") or []

        for output in outputs:
            single_result = DocumentToolResult.success(
                operation="pdf_split_by_ranges",
                source_paths=[source_path],
                output_path=output["output_path"],
                metadata={
                    "range": output.get("range"),
                    "page_count": output.get("page_count"),
                    "parent_result": result.to_dict(),
                },
            )

            generated_items.append(
                _register_generated_result(
                    source_items=[item],
                    result=single_result,
                    operation="pdf_split_by_ranges",
                )
            )

    return {
        "ok": result.ok,
        "operation": "pdf_split_by_ranges",
        "source_item_ids": [item.get("id")],
        "result": result.to_dict(),
        "generated_items": generated_items,
    }


def compress_inbox_pdf(
    inbox_item_id: int,
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.pdf_tools_service import compress_pdf_basic

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = compress_pdf_basic(source_path, output_stem=output_stem)

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="pdf_compress_basic",
    )


def crop_inbox_image(
    inbox_item_id: int,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.image_tools_service import crop_image

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = crop_image(
        source_path,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        output_stem=output_stem,
    )

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="image_crop",
    )

def compress_inbox_pdf_strong(
    inbox_item_id: int,
    *,
    dpi: int = 120,
    jpeg_quality: int = 55,
    grayscale: bool = False,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.pdf_tools_service import compress_pdf_rasterized

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = compress_pdf_rasterized(
        source_path,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
        grayscale=grayscale,
        output_stem=output_stem,
    )

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="pdf_compress_rasterized",
    )

def move_page_in_inbox_pdf(
    inbox_item_id: int,
    *,
    page_number: int,
    target_position: int,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.pdf_tools_service import move_pdf_page

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = move_pdf_page(
        source_path,
        page_number=page_number,
        target_position=target_position,
        output_stem=output_stem,
    )

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="pdf_move_page",
    )

def convert_inbox_word_to_pdf(
    inbox_item_id: int,
    *,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.word_tools_service import word_to_pdf

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = word_to_pdf(
        source_path,
        output_stem=output_stem,
    )

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="word_to_pdf",
    )

def compress_inbox_pdf_smart(
    inbox_item_id: int,
    *,
    dpi: int = 120,
    jpeg_quality: int = 55,
    grayscale: bool = False,
    register_result: bool = True,
    output_stem: str | None = None,
) -> dict[str, Any]:
    from backend.services.document_tools.pdf_tools_service import compress_pdf_smart

    item = _get_item_or_fail(inbox_item_id)
    source_path = _resolve_inbox_item_path(item)

    result = compress_pdf_smart(
        source_path,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
        grayscale=grayscale,
        output_stem=output_stem,
    )

    return _build_operation_response(
        source_items=[item],
        result=result,
        register_result=register_result,
        operation="pdf_compress_smart",
    )

