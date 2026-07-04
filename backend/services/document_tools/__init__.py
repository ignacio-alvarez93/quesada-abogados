from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.document_metadata_service import get_document_metadata
from backend.services.document_tools.image_tools_service import (
    get_image_metadata,
    image_to_pdf,
    images_to_pdf,
)
from backend.services.document_tools.pdf_tools_service import (
    extract_pdf_pages,
    get_pdf_metadata,
    merge_pdfs,
    remove_pdf_pages,
)

__all__ = [
    "DocumentToolResult",
    "get_document_metadata",
    "get_image_metadata",
    "image_to_pdf",
    "images_to_pdf",
    "extract_pdf_pages",
    "get_pdf_metadata",
    "merge_pdfs",
    "remove_pdf_pages",
    "convert_inbox_image_to_pdf",
    "convert_inbox_images_to_pdf",
    "extract_pages_from_inbox_pdf",
    "get_inbox_item_document_metadata",
    "merge_inbox_pdfs",
    "remove_pages_from_inbox_pdf",
    "get_document_tool_capabilities_for_inbox_items",
]

from backend.services.document_tools.document_inbox_tools_service import (
    convert_inbox_image_to_pdf,
    convert_inbox_images_to_pdf,
    extract_pages_from_inbox_pdf,
    get_inbox_item_document_metadata,
    merge_inbox_pdfs,
    remove_pages_from_inbox_pdf,
)

from backend.services.document_tools.document_tool_capabilities_service import (
    get_document_tool_capabilities_for_inbox_items,
)

# Priority document operations exports
try:
    from backend.services.document_tools.pdf_tools_service import (
        compress_pdf_basic,
        reorder_pdf_pages,
        split_pdf_by_ranges,
    )
except Exception:
    pass

try:
    from backend.services.document_tools.image_tools_service import crop_image
except Exception:
    pass

try:
    from backend.services.document_tools.document_inbox_tools_service import (
        compress_inbox_pdf,
        crop_inbox_image,
        reorder_pages_from_inbox_pdf,
        split_inbox_pdf_by_ranges,
    )
except Exception:
    pass
