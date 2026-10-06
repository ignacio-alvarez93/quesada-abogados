"""Viewer lifecycle seam; rendering and file validation stay in the service.

Page requests are independent of Flet controls. A later scheduler can add a
bounded cache, prefetch and eviction here without replacing the viewer API.
"""
from dataclasses import dataclass

from backend.services import document_viewer_service


@dataclass(frozen=True)
class PreviewRequest:
    path: str
    expediente_id: int | str | None
    page_number: int
    zoom: float


class DocumentPreviewSession:
    def __init__(self):
        self.generation = 0
        self._loaded_until = {}

    def invalidate(self):
        self.generation += 1
        return self.generation

    def is_current(self, generation):
        return generation == self.generation

    def initial_extent(self, request: PreviewRequest, total_pages: int):
        key = (request.path, request.expediente_id, request.zoom)
        extent = min(total_pages, max(
            self._loaded_until.get(key, 0), request.page_number + 3,
        ))
        self._loaded_until[key] = extent
        return extent

    def loaded_extent(self, request: PreviewRequest):
        return self._loaded_until.get((request.path, request.expediente_id, request.zoom), 0)

    def record_extent(self, request: PreviewRequest, extent: int):
        self._loaded_until[(request.path, request.expediente_id, request.zoom)] = extent

    def render(self, request: PreviewRequest, generation: int):
        if not self.is_current(generation):
            return {}
        result = document_viewer_service.create_document_preview(
            request.path, expediente_id=request.expediente_id,
            page_number=request.page_number, zoom=request.zoom,
        )
        # Native rendering is synchronous today; discard obsolete results.
        return result if self.is_current(generation) else {}
