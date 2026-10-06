from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from functools import wraps

import mimetypes
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services import expedient_service


PREVIEW_DIR = Path("data/document_previews")

# Dedicated namespace: eviction never touches source documents or legacy previews.
PREVIEW_CACHE_MAX_PAGES = 64
PREVIEW_CACHE_MAX_BYTES = 128 * 1024 * 1024
_preview_lock = threading.RLock()
_preview_clock = 0


def _serialized_preview(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _preview_lock:
            return function(*args, **kwargs)
    return wrapped


def _touch_preview(path):
    global _preview_clock
    _preview_clock = max(time.time_ns(), _preview_clock + 1)
    os.utime(path, ns=(_preview_clock, _preview_clock))


def _evict_previews(directory, *, reserve_pages=0, reserve_bytes=0):
    entries = sorted(
        ((p.stat().st_mtime_ns, p.name, p, p.stat().st_size)
         for p in directory.glob('*.png')),
    )
    size = sum(entry[3] for entry in entries)
    count = len(entries)
    for _, _, path, length in entries:
        if (count + reserve_pages <= PREVIEW_CACHE_MAX_PAGES
                and size + reserve_bytes <= PREVIEW_CACHE_MAX_BYTES):
            break
        path.unlink(missing_ok=True)
        count -= 1
        size -= length


PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff",
    ".doc", ".docx",
    ".xls", ".xlsx",
    ".txt", ".rtf",
    ".odt", ".ods",
}


def _safe_stat(path: Path) -> dict[str, Any]:
    try:
        st = path.stat()
        return {
            "size_bytes": st.st_size,
            "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        }
    except OSError:
        return {
            "size_bytes": None,
            "modified_at": None,
        }


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"

    value = float(size_bytes)
    units = ["B", "KB", "MB", "GB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} GB"


def _normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_inside_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def get_expediente_document_root(expediente_id: int | str) -> dict[str, Any]:
    """
    Devuelve la carpeta raíz documental del expediente.

    Por ahora usamos box_folder_path, que es la carpeta vinculada desde ficha.
    """
    expediente = expedient_service.get_expediente(expediente_id)
    if not expediente:
        raise ValueError("Expediente no encontrado")

    raw_path = str(expediente.get("box_folder_path") or "").strip()
    if not raw_path:
        return {
            "expediente_id": int(expediente_id),
            "root_path": "",
            "exists": False,
            "message": "El expediente no tiene carpeta Box vinculada.",
        }

    root = _normalize_path(raw_path)
    return {
        "expediente_id": int(expediente_id),
        "root_path": str(root),
        "exists": root.exists() and root.is_dir(),
        "message": "" if root.exists() and root.is_dir() else "La carpeta Box vinculada no existe en este equipo.",
    }


def list_expediente_documents(
    expediente_id: int | str,
    max_files: int = 1000,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """
    Lista todos los documentos bajo la carpeta Box vinculada al expediente.

    Recorre todas las subcarpetas. No modifica Box.
    """
    root_info = get_expediente_document_root(expediente_id)
    root_path = root_info.get("root_path") or ""

    if not root_info.get("exists"):
        return {
            **root_info,
            "documents": [],
            "total_documents": 0,
        }

    root = _normalize_path(root_path)
    documents: list[dict[str, Any]] = []

    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)

        if not include_hidden:
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and not d.startswith("~")
            ]

        for filename in filenames:
            if len(documents) >= max_files:
                break

            if not include_hidden and (filename.startswith(".") or filename.startswith("~")):
                continue

            file_path = (current_path / filename).resolve()
            if not _is_inside_root(file_path, root):
                continue

            ext = file_path.suffix.lower()
            if ext not in DOCUMENT_EXTENSIONS:
                continue

            stat = _safe_stat(file_path)
            mime_type, _ = mimetypes.guess_type(str(file_path))

            relative_path = str(file_path.relative_to(root))
            folder_relative = str(file_path.parent.relative_to(root)) if file_path.parent != root else ""

            doc_type = "pdf" if ext in PDF_EXTENSIONS else "image" if ext in IMAGE_EXTENSIONS else "document"

            documents.append(
                {
                    "name": file_path.name,
                    "path": str(file_path),
                    "relative_path": relative_path,
                    "folder_relative": folder_relative,
                    "extension": ext,
                    "mime_type": mime_type,
                    "type": doc_type,
                    "size_bytes": stat["size_bytes"],
                    "size_label": _format_size(stat["size_bytes"]),
                    "modified_at": stat["modified_at"],
                    "previewable": ext in PDF_EXTENSIONS or ext in IMAGE_EXTENSIONS,
                }
            )

        if len(documents) >= max_files:
            break

    documents.sort(
        key=lambda item: (
            str(item.get("folder_relative") or "").upper(),
            str(item.get("name") or "").upper(),
        )
    )

    return {
        **root_info,
        "documents": documents,
        "total_documents": len(documents),
    }


def open_document(path: str, expediente_id: int | str | None = None) -> dict[str, Any]:
    """
    Abre un documento con el visor del sistema.

    Si expediente_id se pasa, valida que el archivo está dentro de la carpeta Box vinculada.
    """
    file_path = _normalize_path(path)

    if expediente_id is not None:
        root_info = get_expediente_document_root(expediente_id)
        if not root_info.get("exists"):
            raise ValueError(root_info.get("message") or "Carpeta raíz no disponible")

        root = _normalize_path(root_info["root_path"])
        if not _is_inside_root(file_path, root):
            raise ValueError("El archivo no pertenece a la carpeta documental del expediente.")

    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError("El documento no existe.")

    system = platform.system().lower()

    if system == "windows":
        os.startfile(str(file_path))  # type: ignore[attr-defined]
    elif system == "darwin":
        subprocess.Popen(["open", str(file_path)])
    else:
        subprocess.Popen(["xdg-open", str(file_path)])

    return {
        "ok": True,
        "path": str(file_path),
    }


@_serialized_preview
def create_document_preview(path: str, expediente_id: int | str | None = None, page_number: int = 1, zoom: float = 1.6) -> dict[str, Any]:
    """
    Crea o devuelve una preview para Flet.

    - Imágenes: devuelve la propia ruta.
    - PDF: intenta renderizar primera página con PyMuPDF.
    - Otros: no previewable.

    Para PDF integrado hace falta:
        pip install PyMuPDF
    """
    file_path = _normalize_path(path)

    if expediente_id is not None:
        root_info = get_expediente_document_root(expediente_id)
        if not root_info.get("exists"):
            raise ValueError(root_info.get("message") or "Carpeta raíz no disponible")

        root = _normalize_path(root_info["root_path"])
        if not _is_inside_root(file_path, root):
            raise ValueError("El archivo no pertenece a la carpeta documental del expediente.")

    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError("El documento no existe.")

    ext = file_path.suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        return {
            "ok": True,
            "preview_type": "image",
            "preview_path": str(file_path),
            "message": "",
        }

    if ext not in PDF_EXTENSIONS:
        return {
            "ok": False,
            "preview_type": "unsupported",
            "preview_path": "",
            "message": "Este tipo de documento no tiene preview integrada todavía.",
        }

    try:
        import fitz  # PyMuPDF
    except Exception:
        return {
            "ok": False,
            "preview_type": "pdf",
            "preview_path": "",
            "message": "PyMuPDF no está instalado. Ejecuta: pip install PyMuPDF",
        }

    cache_dir = PREVIEW_DIR / "v2"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _evict_previews(cache_dir)

    try:
        requested_page = max(1, int(page_number or 1))
    except Exception:
        requested_page = 1

    try:
        render_zoom = float(zoom or 1.6)
    except Exception:
        render_zoom = 1.6

    if not math.isfinite(render_zoom):
        render_zoom = 1.6
    render_zoom = max(0.8, min(render_zoom, 3.5))

    doc = None
    try:
        # Render the same immutable snapshot whose digest identifies the cache.
        source_bytes = file_path.read_bytes()
        source_digest = hashlib.sha256(source_bytes).hexdigest()
        doc = fitz.open(stream=source_bytes, filetype="pdf")
        total_pages = len(doc)
        if total_pages == 0:
            return {
                "ok": False,
                "preview_type": "pdf",
                "preview_path": "",
                "message": "El PDF no tiene páginas.",
                "page_number": 1,
                "total_pages": 0,
            }

        current_page = min(max(1, requested_page), total_pages)
        key = json.dumps([
            "viewer-v2-png-rgb-alpha-false", str(file_path), source_digest,
            str(expediente_id) if expediente_id is not None else None,
            current_page, render_zoom.hex(), fitz.VersionBind,
        ], ensure_ascii=True, separators=(",", ":"))
        preview_path = cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".png")
        if not preview_path.is_file():
            page = doc.load_page(current_page - 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(render_zoom, render_zoom), alpha=False)
            png = pix.tobytes("png")
            if PREVIEW_CACHE_MAX_PAGES < 1 or len(png) > PREVIEW_CACHE_MAX_BYTES:
                raise ValueError("Rendered page exceeds preview cache budget")
            _evict_previews(cache_dir, reserve_pages=1, reserve_bytes=len(png))
            temporary = preview_path.with_suffix(".tmp")
            try:
                temporary.write_bytes(png)
                temporary.replace(preview_path)
            finally:
                temporary.unlink(missing_ok=True)
        _touch_preview(preview_path)

        return {
            "ok": True,
            "preview_type": "pdf",
            "preview_path": str(preview_path.resolve()),
            "message": "",
            "page_number": current_page,
            "total_pages": total_pages,
            "zoom": render_zoom,
        }
    except Exception as exc:
        return {
            "ok": False,
            "preview_type": "pdf",
            "preview_path": "",
            "message": f"No se pudo generar preview PDF: {exc}",
        }

    finally:
        if doc is not None:
            doc.close()
