from pathlib import Path
from datetime import datetime
import re


def _file_url_from_path(path):
    try:
        return Path(path).resolve().as_uri()
    except Exception:
        return str(path or "")


def _relative_path(path, base):
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve()))
    except Exception:
        try:
            return str(Path(path).name)
        except Exception:
            return str(path or "")


def _numeric_name_sort_key(name):
    """
    Orden Mercurio visible y estable.

    Primero archivos con prefijo numérico:
        1_PASAPORTE.pdf
        02_PADRON.pdf
        10_TASA.pdf

    Después archivos sin número, por orden alfabético.
    """
    text = str(name or "").strip()
    match = re.match(r"^\s*(\d+)(?:[\s._-]+|$)", text)
    if match:
        return (0, int(match.group(1)), text.lower())
    return (1, 999999, text.lower())


def _numeric_order_label(name):
    text = str(name or "").strip()
    match = re.match(r"^\s*(\d+)(?:[\s._-]+|$)", text)
    if match:
        return str(int(match.group(1))).zfill(2)
    return "-"


def list_expediente_box_directory(path, relative_base=None):
    """
    Explorador readonly de carpetas Box/locales.

    No crea, mueve, borra ni renombra documentos.

    Devuelve:
    {
        "current_path": "...",
        "folders": [...],
        "files": [...]
    }
    """

    root = Path(str(path or "").strip())
    base = Path(str(relative_base or path or "").strip())

    if not root.exists():
        raise FileNotFoundError(f"No existe la ruta: {root}")

    if not root.is_dir():
        raise NotADirectoryError(f"La ruta no es una carpeta: {root}")

    folders = []
    files = []

    for child in root.iterdir():
        try:
            if child.is_dir():
                stat = child.stat()
                folders.append({
                    "name": child.name,
                    "path": str(child),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "relative_path": _relative_path(child, base),
                    "box_folder_id": None,
                    "box_url": _file_url_from_path(child),
                })
            elif child.is_file():
                stat = child.stat()
                extension = child.suffix.lower().lstrip(".")
                files.append({
                    "name": child.name,
                    "order_label": _numeric_order_label(child.name),
                    "sort_key": _numeric_name_sort_key(child.name),
                    "path": str(child),
                    "extension": extension,
                    "size": int(stat.st_size or 0),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "fecha_modificacion": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "box_file_id": None,
                    "relative_path": _relative_path(child, base),
                    "box_url": _file_url_from_path(child),
                })
        except Exception:
            continue

    folders.sort(key=lambda item: str(item.get("name") or "").lower())
    files.sort(key=lambda item: _numeric_name_sort_key(item.get("name")))

    return {
        "current_path": str(root),
        "folders": folders,
        "files": files,
    }


def list_para_presentar_documents(folder_path, relative_base=None):
    """
    Lista documentos directos de la carpeta PARA PRESENTAR.
    Solo lectura. No accede a Mercurio.
    """
    data = list_expediente_box_directory(folder_path, relative_base=relative_base or folder_path)
    return data.get("files") or []
