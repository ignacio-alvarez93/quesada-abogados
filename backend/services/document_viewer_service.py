from __future__ import annotations

import mimetypes
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.services import expedient_service


PREVIEW_DIR = Path("data/document_previews")

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


def create_document_preview(path: str, expediente_id: int | str | None = None, page_number: int = 1) -> dict[str, Any]:
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

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        requested_page = max(1, int(page_number or 1))
    except Exception:
        requested_page = 1

    safe_name = f"{abs(hash(str(file_path)))}_p{requested_page}.png"
    preview_path = PREVIEW_DIR / safe_name

    try:
        doc = fitz.open(str(file_path))
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
        page = doc.load_page(current_page - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
        pix.save(str(preview_path))
        doc.close()

        return {
            "ok": True,
            "preview_type": "pdf",
            "preview_path": str(preview_path.resolve()),
            "message": "",
            "page_number": current_page,
            "total_pages": total_pages,
        }
    except Exception as exc:
        return {
            "ok": False,
            "preview_type": "pdf",
            "preview_path": "",
            "message": f"No se pudo generar preview PDF: {exc}",
        }
