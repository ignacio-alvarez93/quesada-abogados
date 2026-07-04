from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOCUMENT_TOOLS_ROOT = PROJECT_ROOT / "storage" / "document_tools"


def ensure_document_tools_dirs() -> None:
    for relative in (
        "pdf",
        "images",
        "converted",
        "merged",
        "split",
        "compressed",
        "temp",
    ):
        (DOCUMENT_TOOLS_ROOT / relative).mkdir(parents=True, exist_ok=True)


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate

    return candidate.resolve()


def assert_existing_file(path: str | Path) -> Path:
    resolved = resolve_project_path(path)

    if not resolved.exists():
        raise FileNotFoundError(f"No existe el archivo: {resolved}")

    if not resolved.is_file():
        raise ValueError(f"La ruta no es un archivo: {resolved}")

    return resolved


def build_output_path(
    *,
    operation: str,
    source_path: str | Path | None = None,
    extension: str,
    subdir: str,
    stem: str | None = None,
) -> Path:
    ensure_document_tools_dirs()

    clean_ext = extension if extension.startswith(".") else f".{extension}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = uuid4().hex[:8]

    if stem:
        base_name = stem
    elif source_path:
        base_name = Path(source_path).stem
    else:
        base_name = "document"

    safe_base = "".join(
        c if c.isalnum() or c in ("-", "_") else "_"
        for c in base_name
    ).strip("_") or "document"

    filename = f"{timestamp}_{operation}_{safe_base}_{suffix}{clean_ext}"
    output_dir = DOCUMENT_TOOLS_ROOT / subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    return output_dir / filename


def copy_to_temp(source_path: str | Path) -> Path:
    source = assert_existing_file(source_path)
    target = build_output_path(
        operation="temp_copy",
        source_path=source,
        extension=source.suffix or ".bin",
        subdir="temp",
    )
    shutil.copy2(source, target)
    return target


def file_metadata(path: str | Path) -> dict:
    resolved = assert_existing_file(path)
    stat = resolved.stat()

    return {
        "filename": resolved.name,
        "suffix": resolved.suffix.lower(),
        "size_bytes": stat.st_size,
        "path": str(resolved),
    }
