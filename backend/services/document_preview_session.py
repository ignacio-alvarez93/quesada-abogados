"""Viewer lifecycle seam; rendering and file validation stay in the service.

Page requests and bounded window state are independent of Flet controls.
"""
import hashlib
import threading
from contextlib import contextmanager
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
        self._condition = threading.Condition(threading.RLock())
        self._active = False
        self._closed = False
        self.near_window = near_window
        self.requested_window = ()
        self.loaded_window = {}
        self.current_request = None
        self._window_key = None
        self.generation = 0
        self._loaded_until = {}
        self._resources = None
        self._document_key = None

    def invalidate(self):
        with self._condition:
            self.generation += 1
            self._condition.notify_all()
            return self.generation

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self.invalidate()
            self.requested_window = ()
            self.loaded_window = {}
            self.current_request = None
            self._window_key = None
            self._loaded_until.clear()
            resources, self._resources = self._resources, None
            self._document_key = None
        if resources is not None:
            resources.close()

    dispose = close

    def is_current(self, generation):
        with self._condition:
            return not self._closed and generation == self.generation

    @contextmanager
    def publication(self, generation):
        """Serialize UI/state publication against navigation and close."""
        with self._condition:
            yield self.is_current(generation)

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
        """One active window; only the latest generation may wait or publish.

        Native rendering is not interrupted. Superseded waiters return empty;
        active obsolete work stops at the next page boundary. No executor queue
        or worker lifetime is introduced into Flet's synchronous handlers.
        """
        with self._condition:
            while self._active and self.is_current(generation):
                self._condition.wait()
            if not self.is_current(generation):
                return {}
            document_key = (str(Path(request.path).resolve()), request.expediente_id)
            if document_key != self._document_key:
                if self._resources is not None:
                    self._resources.close()
                self._resources = document_viewer_service.PreviewResources()
                self._document_key = document_key
                self.loaded_window.clear()
                self.requested_window = ()
                self.current_request = None
                self._window_key = None
                self._loaded_until.clear()
            self._active = True
        try:
            return self._render_window(request, generation)
        finally:
            with self._condition:
                self._active = False
                self._condition.notify_all()

    def _render_window(self, request: PreviewRequest, generation: int):
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
                   stat.st_mtime_ns, stat.st_size,
                   hashlib.sha256(source.read_bytes()).hexdigest())
        except OSError:
            key = None
        previous = self.loaded_window if key is not None and key == self._window_key else {}
        previous = {number: result for number, result in previous.items()
                    if Path(result.get("preview_path", "")).is_file()}
        with self.publication(generation) as current_generation:
            if not current_generation:
                return {}
            self.requested_window = ()
            self.loaded_window = {}
            self.current_request = None
        loaded = {}
        preview = self.render(request, generation)
        if not self.is_current(generation) or not preview.get("ok"):
            return preview
        current = int(preview.get("page_number") or 1)
        current_request = replace(request, page_number=current)
        total = int(preview.get("total_pages") or 1)
        numbers = tuple(range(max(1, current - self.near_window),
                              min(total, current + self.near_window) + 1))
        for number in numbers:
            if not self.is_current(generation):
                return {}
            try:
                retained = previous.get(number)
                if retained and not Path(retained.get("preview_path", "")).is_file():
                    retained = None
                # Prefetch may fill the budget, but must not evict this window's
                # current page or any neighbor already retained for publication.
                result = (preview if number == current else retained
                          or self.render(replace(request, page_number=number), generation,
                                         protected_paths=[preview["preview_path"]] + [
                                             item["preview_path"] for item in loaded.values()]))
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            if not self.is_current(generation):
                return {}
            if result.get("ok") and result.get("preview_path"):
                loaded[number] = result
        with self.publication(generation) as current_generation:
            if not current_generation:
                return {}
            self.current_request = current_request
            self.requested_window = numbers
            self.loaded_window = loaded
            self._window_key = key
        return preview

    def render(self, request: PreviewRequest, generation: int, *, protected_paths=()):
        if not self.is_current(generation):
            return {}
        result = document_viewer_service.create_document_preview(
            request.path, expediente_id=request.expediente_id,
            page_number=request.page_number, zoom=request.zoom,
            resources=self._resources, is_current=lambda: not self._closed and generation == self.generation,
            protected_paths=protected_paths,
        )
        # Native rendering is synchronous today; discard obsolete results.
        return result if self.is_current(generation) else {}
