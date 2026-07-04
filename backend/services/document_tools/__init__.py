from __future__ import annotations

from backend.services.document_tools.document_tool_result import DocumentToolResult

from backend.services.document_tools.document_metadata_service import (
    get_document_metadata,
)

from backend.services.document_tools.pdf_tools_service import (
    compress_pdf_basic,
    compress_pdf_rasterized,
    extract_pdf_pages,
    get_pdf_metadata,
    merge_pdfs,
    move_pdf_page,
    remove_pdf_pages,
    reorder_pdf_pages,
    split_pdf_by_ranges,
)

from backend.services.document_tools.image_tools_service import (
    crop_image,
    get_image_metadata,
    image_to_pdf,
    images_to_pdf,
)

from backend.services.document_tools.word_tools_service import (
    word_to_pdf,
)

from backend.services.document_tools.document_inbox_tools_service import (
    compress_inbox_pdf,
    compress_inbox_pdf_strong,
    convert_inbox_image_to_pdf,
    convert_inbox_images_to_pdf,
    convert_inbox_word_to_pdf,
    crop_inbox_image,
    extract_pages_from_inbox_pdf,
    get_inbox_item_document_metadata,
    merge_inbox_pdfs,
    move_page_in_inbox_pdf,
    remove_pages_from_inbox_pdf,
    reorder_pages_from_inbox_pdf,
    split_inbox_pdf_by_ranges,
)

from backend.services.document_tools.document_tool_capabilities_service import (
    get_document_tool_capabilities_for_inbox_items,
)


__all__ = [
    "DocumentToolResult",

    # Metadata
    "get_document_metadata",
    "get_pdf_metadata",
    "get_image_metadata",

    # Core PDF tools
    "compress_pdf_basic",
    "compress_inbox_pdf_strong",
    "compress_pdf_rasterized",
    "extract_pdf_pages",
    "merge_pdfs",
    "move_pdf_page",
    "remove_pdf_pages",
    "reorder_pdf_pages",
    "split_pdf_by_ranges",

    # Core image tools
    "crop_image",
    "image_to_pdf",
    "images_to_pdf",
    "word_to_pdf",

    # Inbox adapter tools
    "compress_inbox_pdf",
    "convert_inbox_image_to_pdf",
    "convert_inbox_images_to_pdf",
    "convert_inbox_word_to_pdf",
    "crop_inbox_image",
    "extract_pages_from_inbox_pdf",
    "get_inbox_item_document_metadata",
    "merge_inbox_pdfs",
    "move_page_in_inbox_pdf",
    "remove_pages_from_inbox_pdf",
    "reorder_pages_from_inbox_pdf",
    "split_inbox_pdf_by_ranges",

    # Capabilities
    "get_document_tool_capabilities_for_inbox_items",
]
