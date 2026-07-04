from __future__ import annotations

from pathlib import Path

from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.safe_file_service import (
    assert_existing_file,
    build_output_path,
    file_metadata,
)

try:
    from PIL import Image
except Exception:  # pragma: no cover - dependencia no instalada todavía
    Image = None


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _require_pillow() -> None:
    if Image is None:
        raise RuntimeError(
            "Falta la dependencia Pillow. Instala o añade en requirements.txt: Pillow"
        )


def get_image_metadata(source_path: str | Path) -> DocumentToolResult:
    operation = "image_metadata"

    try:
        _require_pillow()
        source = assert_existing_file(source_path)

        if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError(f"Formato de imagen no soportado: {source.suffix}")

        with Image.open(source) as img:
            metadata = file_metadata(source)
            metadata.update(
                {
                    "width": img.width,
                    "height": img.height,
                    "mode": img.mode,
                    "format": img.format,
                    "mime_type": Image.MIME.get(img.format, None),
                }
            )

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=source,
            metadata=metadata,
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def image_to_pdf(source_path: str | Path, output_stem: str | None = None) -> DocumentToolResult:
    operation = "image_to_pdf"

    try:
        _require_pillow()
        source = assert_existing_file(source_path)

        if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError(f"Formato de imagen no soportado: {source.suffix}")

        output = build_output_path(
            operation="image_to_pdf",
            source_path=source,
            extension=".pdf",
            subdir="converted",
            stem=output_stem,
        )

        with Image.open(source) as img:
            rgb = img.convert("RGB")
            rgb.save(output, "PDF", resolution=100.0)

            metadata = {
                "source_width": img.width,
                "source_height": img.height,
                "source_format": img.format,
                "mime_type": "application/pdf",
                "size_bytes": output.stat().st_size,
            }

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            metadata=metadata,
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def images_to_pdf(source_paths: list[str | Path], output_stem: str | None = None) -> DocumentToolResult:
    operation = "images_to_pdf"

    try:
        _require_pillow()

        if not source_paths:
            raise ValueError("Debe indicarse al menos una imagen.")

        sources = [assert_existing_file(path) for path in source_paths]

        for source in sources:
            if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                raise ValueError(f"Formato de imagen no soportado: {source.suffix}")

        output = build_output_path(
            operation="images_to_pdf",
            extension=".pdf",
            subdir="converted",
            stem=output_stem or "imagenes_unidas",
        )

        opened_images = []
        rgb_images = []

        try:
            for source in sources:
                img = Image.open(source)
                opened_images.append(img)
                rgb_images.append(img.convert("RGB"))

            first, rest = rgb_images[0], rgb_images[1:]
            first.save(output, "PDF", save_all=True, append_images=rest, resolution=100.0)

        finally:
            for img in opened_images:
                img.close()

        return DocumentToolResult.success(
            operation=operation,
            source_paths=sources,
            output_path=output,
            metadata={
                "source_count": len(sources),
                "page_count": len(sources),
                "mime_type": "application/pdf",
                "size_bytes": output.stat().st_size,
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=source_paths,
            errors=[str(exc)],
        )
