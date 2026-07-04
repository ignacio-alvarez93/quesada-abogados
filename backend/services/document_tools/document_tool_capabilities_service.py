from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.document_inbox_service import get_inbox_item


PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
WORD_EXTENSIONS = {".docx", ".doc"}


def get_document_tool_capabilities_for_inbox_items(inbox_item_ids: list[int]) -> dict[str, Any]:
    """
    Devuelve las operaciones documentales disponibles para una selección
    de items de Bandeja Documental.

    Esta función no ejecuta operaciones.
    Solo ayuda a la UI a mostrar acciones válidas.
    """
    clean_ids = [int(x) for x in inbox_item_ids if x is not None]

    if not clean_ids:
        return {
            "ok": True,
            "selection_count": 0,
            "items": [],
            "capabilities": [],
            "warnings": ["No hay documentos seleccionados."],
        }

    items = [get_inbox_item(item_id) for item_id in clean_ids]
    items = [item for item in items if item]

    missing_ids = [item_id for item_id in clean_ids if not any(item.get("id") == item_id for item in items)]

    descriptors = [_describe_item(item) for item in items]
    categories = {d["category"] for d in descriptors}

    capabilities = []

    if len(items) == 1:
        item = descriptors[0]

        capabilities.append(
            {
                "operation": "metadata",
                "label": "Ver metadatos",
                "scope": "single",
                "enabled": True,
                "reason": "",
            }
        )

        if item["category"] == "image":
            capabilities.extend(
                [
                    {
                        "operation": "image_crop",
                        "label": "Recortar imagen",
                        "scope": "single",
                        "enabled": True,
                        "reason": "",
                        "priority": 10,
                    },
                    {
                        "operation": "image_to_pdf",
                        "label": "Convertir imagen a PDF",
                        "scope": "single",
                        "enabled": True,
                        "reason": "",
                        "priority": 40,
                    },
                ]
            )

        if item["category"] == "word":
            capabilities.append(
                {
                    "operation": "word_to_pdf",
                    "label": "Convertir Word a PDF",
                    "scope": "single",
                    "enabled": True,
                    "reason": "",
                    "priority": 35,
                }
            )

        if item["category"] == "pdf":
            capabilities.extend(
                [
                    {
                        "operation": "pdf_reorder_pages",
                        "label": "Ordenar páginas",
                        "scope": "single",
                        "enabled": True,
                        "reason": "",
                        "priority": 10,
                    },
                    {
                        "operation": "pdf_split_by_ranges",
                        "label": "Dividir PDF",
                        "scope": "single",
                        "enabled": True,
                        "reason": "",
                        "priority": 20,
                    },
                    {
                        "operation": "pdf_compress_basic",
                        "label": "Comprimir PDF",
                        "scope": "single",
                        "enabled": True,
                        "reason": "",
                        "priority": 30,
                    },
                    {
                        "operation": "pdf_extract_pages",
                        "label": "Extraer páginas",
                        "scope": "single",
                        "enabled": True,
                        "reason": "",
                        "priority": 40,
                    },
                    {
                        "operation": "pdf_remove_pages",
                        "label": "Eliminar páginas generando copia",
                        "scope": "single",
                        "enabled": True,
                        "reason": "",
                        "priority": 50,
                    },
                ]
            )

    if len(items) >= 2:
        all_images = categories == {"image"}
        all_pdfs = categories == {"pdf"}

        capabilities.append(
            {
                "operation": "metadata_batch",
                "label": "Ver metadatos de selección",
                "scope": "batch",
                "enabled": True,
                "reason": "",
            }
        )

        capabilities.append(
            {
                "operation": "images_to_pdf",
                "label": "Convertir imágenes a PDF único",
                "scope": "batch",
                "enabled": all_images,
                "reason": "" if all_images else "Solo disponible si todos los seleccionados son imágenes.",
            }
        )

        capabilities.append(
            {
                "operation": "pdf_merge",
                "label": "Unir PDFs",
                "scope": "batch",
                "enabled": all_pdfs,
                "reason": "" if all_pdfs else "Solo disponible si todos los seleccionados son PDFs.",
                "priority": 20,
            }
        )

    return {
        "ok": True,
        "selection_count": len(items),
        "requested_ids": clean_ids,
        "missing_ids": missing_ids,
        "items": descriptors,
        "capabilities": capabilities,
        "warnings": _build_warnings(descriptors, missing_ids),
    }


def _describe_item(item: dict[str, Any]) -> dict[str, Any]:
    original_filename = item.get("original_filename") or ""
    stored_filename = item.get("stored_filename") or ""
    stored_path = item.get("stored_path") or ""

    suffix = (
        Path(original_filename).suffix
        or Path(stored_filename).suffix
        or Path(stored_path).suffix
        or ""
    ).lower()

    mime_type = (item.get("mime_type") or "").lower()

    category = _guess_category(suffix=suffix, mime_type=mime_type)

    return {
        "id": item.get("id"),
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "stored_path": stored_path,
        "suffix": suffix,
        "mime_type": item.get("mime_type"),
        "status": item.get("status"),
        "client_id": item.get("client_id"),
        "expedient_id": item.get("expedient_id"),
        "category": category,
        "supported": category in {"pdf", "image"},
    }


def _guess_category(*, suffix: str, mime_type: str) -> str:
    if suffix in PDF_EXTENSIONS or mime_type == "application/pdf":
        return "pdf"

    if suffix in IMAGE_EXTENSIONS or mime_type.startswith("image/"):
        return "image"

    if suffix in {".doc", ".docx"}:
        return "word"

    if suffix in {".xls", ".xlsx", ".csv"}:
        return "spreadsheet"

    return "other"


def _build_warnings(descriptors: list[dict[str, Any]], missing_ids: list[int]) -> list[str]:
    warnings = []

    if missing_ids:
        warnings.append(f"No se encontraron algunos items: {missing_ids}")

    unsupported = [d for d in descriptors if not d["supported"]]

    if unsupported:
        warnings.append(
            "Hay documentos seleccionados que todavía no tienen herramientas disponibles: "
            + ", ".join(str(d["id"]) for d in unsupported)
        )

    return warnings
