"""Viewer lifecycle seam; rendering and file validation stay in the service.

Page requests and bounded window state are independent of Flet controls.
"""
from dataclasses import dataclass, replace
from pathlib import Path

from backend.services import document_viewer_service


@dataclass(frozen=True)
class PreviewRequest:
    path: str
    expediente_id: int | str | None
    page_number: int
    zoom: float


class DocumentPreviewSession:
    def __init__(self, near_window: int = 3):
        if not isinstance(near_window, int) or near_window < 0:
            raise ValueError("near_window must be a non-negative integer")
        self.near_window = near_window
        self.requested_window = ()
        self.loaded_window = {}
        self.current_request = None
        self._window_key = None
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

    def render_window(self, request: PreviewRequest, generation: int):
        """Resolve the current page, then render only its bounded neighborhood.

        Only successful results belong to loaded_window; failed neighbors remain
        requested and are retried on the next request. Retain overlap only for an
        unchanged source, scope and scale. No document bytes are written here.
        """
        if not self.is_current(generation):
            return {}
        source = Path(request.path)
        try:
            stat = source.stat()
            key = (str(source.resolve()), request.expediente_id, request.zoom,
                   stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = None
        previous = self.loaded_window if key is not None and key == self._window_key else {}
        self.requested_window = ()
        self.loaded_window = {}
        self.current_request = None
        self._window_key = key
        preview = self.render(request, generation)
        if not self.is_current(generation) or not preview.get("ok"):
            return preview
        current = int(preview.get("page_number") or 1)
        self.current_request = replace(request, page_number=current)
        total = int(preview.get("total_pages") or 1)
        numbers = tuple(range(max(1, current - self.near_window),
                              min(total, current + self.near_window) + 1))
        self.requested_window = numbers
        for number in numbers:
            if not self.is_current(generation):
                return {}
            try:
                result = (preview if number == current else previous.get(number)
                          or self.render(replace(request, page_number=number), generation))
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            if not self.is_current(generation):
                return {}
            if result.get("ok") and result.get("preview_path"):
                self.loaded_window[number] = result
        return preview

    def render(self, request: PreviewRequest, generation: int):
        if not self.is_current(generation):
            return {}
        result = document_viewer_service.create_document_preview(
            request.path, expediente_id=request.expediente_id,
            page_number=request.page_number, zoom=request.zoom,
        )
        # Native rendering is synchronous today; discard obsolete results.
        return result if self.is_current(generation) else {}
