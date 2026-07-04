from __future__ import annotations

from pathlib import Path

from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.safe_file_service import (
    assert_existing_file,
    build_output_path,
    file_metadata,
)

try:
    from pypdf import PdfReader, PdfWriter
except Exception:  # pragma: no cover - dependencia no instalada todavía
    PdfReader = None
    PdfWriter = None


def _require_pypdf() -> None:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError(
            "Falta la dependencia pypdf. Instala o añade en requirements.txt: pypdf"
        )


def get_pdf_metadata(source_path: str | Path) -> DocumentToolResult:
    operation = "pdf_metadata"

    try:
        _require_pypdf()
        source = assert_existing_file(source_path)
        reader = PdfReader(str(source))

        metadata = file_metadata(source)
        metadata.update(
            {
                "page_count": len(reader.pages),
                "is_encrypted": bool(reader.is_encrypted),
                "mime_type": "application/pdf",
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


def merge_pdfs(source_paths: list[str | Path], output_stem: str | None = None) -> DocumentToolResult:
    operation = "pdf_merge"

    try:
        _require_pypdf()

        if len(source_paths) < 2:
            raise ValueError("Para unir PDFs se necesitan al menos 2 archivos.")

        sources = [assert_existing_file(path) for path in source_paths]
        writer = PdfWriter()
        total_pages = 0

        for source in sources:
            reader = PdfReader(str(source))
            if reader.is_encrypted:
                raise ValueError(f"PDF cifrado/no soportado: {source.name}")

            for page in reader.pages:
                writer.add_page(page)
                total_pages += 1

        output = build_output_path(
            operation="merge",
            extension=".pdf",
            subdir="merged",
            stem=output_stem or "pdf_unido",
        )

        with output.open("wb") as fh:
            writer.write(fh)

        return DocumentToolResult.success(
            operation=operation,
            source_paths=sources,
            output_path=output,
            metadata={
                "page_count": total_pages,
                "source_count": len(sources),
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


def extract_pdf_pages(
    source_path: str | Path,
    pages: list[int],
    output_stem: str | None = None,
) -> DocumentToolResult:
    """
    Extrae páginas de un PDF generando una copia nueva.

    pages usa numeración humana: [1, 2, 5].
    """
    operation = "pdf_extract_pages"

    try:
        _require_pypdf()
        source = assert_existing_file(source_path)

        if not pages:
            raise ValueError("Debe indicarse al menos una página.")

        reader = PdfReader(str(source))

        if reader.is_encrypted:
            raise ValueError(f"PDF cifrado/no soportado: {source.name}")

        page_count = len(reader.pages)
        invalid = [p for p in pages if p < 1 or p > page_count]

        if invalid:
            raise ValueError(
                f"Páginas fuera de rango: {invalid}. El PDF tiene {page_count} páginas."
            )

        writer = PdfWriter()

        for page_number in pages:
            writer.add_page(reader.pages[page_number - 1])

        output = build_output_path(
            operation="extract",
            source_path=source,
            extension=".pdf",
            subdir="split",
            stem=output_stem,
        )

        with output.open("wb") as fh:
            writer.write(fh)

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            metadata={
                "source_page_count": page_count,
                "output_page_count": len(pages),
                "selected_pages": pages,
                "mime_type": "application/pdf",
                "size_bytes": output.stat().st_size,
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def remove_pdf_pages(
    source_path: str | Path,
    pages_to_remove: list[int],
    output_stem: str | None = None,
) -> DocumentToolResult:
    """
    Elimina páginas generando copia nueva.
    pages_to_remove usa numeración humana: [1, 3].
    """
    operation = "pdf_remove_pages"

    try:
        _require_pypdf()
        source = assert_existing_file(source_path)

        if not pages_to_remove:
            raise ValueError("Debe indicarse al menos una página a eliminar.")

        reader = PdfReader(str(source))

        if reader.is_encrypted:
            raise ValueError(f"PDF cifrado/no soportado: {source.name}")

        page_count = len(reader.pages)
        invalid = [p for p in pages_to_remove if p < 1 or p > page_count]

        if invalid:
            raise ValueError(
                f"Páginas fuera de rango: {invalid}. El PDF tiene {page_count} páginas."
            )

        remove_set = set(pages_to_remove)
        pages_to_keep = [i for i in range(1, page_count + 1) if i not in remove_set]

        if not pages_to_keep:
            raise ValueError("La operación dejaría el PDF sin páginas.")

        writer = PdfWriter()

        for page_number in pages_to_keep:
            writer.add_page(reader.pages[page_number - 1])

        output = build_output_path(
            operation="remove_pages",
            source_path=source,
            extension=".pdf",
            subdir="split",
            stem=output_stem,
        )

        with output.open("wb") as fh:
            writer.write(fh)

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            metadata={
                "source_page_count": page_count,
                "output_page_count": len(pages_to_keep),
                "removed_pages": pages_to_remove,
                "mime_type": "application/pdf",
                "size_bytes": output.stat().st_size,
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )

def reorder_pdf_pages(
    source_path: str | Path,
    ordered_pages: list[int],
    output_stem: str | None = None,
) -> DocumentToolResult:
    operation = "pdf_reorder_pages"

    try:
        _require_pypdf()
        source = assert_existing_file(source_path)
        reader = PdfReader(str(source))

        if reader.is_encrypted:
            raise ValueError(f"PDF cifrado/no soportado: {source.name}")

        page_count = len(reader.pages)

        if not ordered_pages:
            raise ValueError("Debe indicarse el nuevo orden de páginas.")

        expected = set(range(1, page_count + 1))
        received = set(int(x) for x in ordered_pages)

        if received != expected or len(ordered_pages) != page_count:
            raise ValueError(
                "El nuevo orden debe contener todas las páginas exactamente una vez. "
                f"PDF={page_count} páginas, recibido={ordered_pages}"
            )

        writer = PdfWriter()

        for page_number in ordered_pages:
            writer.add_page(reader.pages[int(page_number) - 1])

        output = build_output_path(
            operation="reorder",
            source_path=source,
            extension=".pdf",
            subdir="split",
            stem=output_stem,
        )

        with output.open("wb") as fh:
            writer.write(fh)

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            metadata={
                "source_page_count": page_count,
                "output_page_count": page_count,
                "ordered_pages": [int(x) for x in ordered_pages],
                "mime_type": "application/pdf",
                "size_bytes": output.stat().st_size,
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def split_pdf_by_ranges(
    source_path: str | Path,
    ranges: list[tuple[int, int]],
    output_stem: str | None = None,
) -> DocumentToolResult:
    operation = "pdf_split_by_ranges"

    try:
        _require_pypdf()
        source = assert_existing_file(source_path)
        reader = PdfReader(str(source))

        if reader.is_encrypted:
            raise ValueError(f"PDF cifrado/no soportado: {source.name}")

        if not ranges:
            raise ValueError("Debe indicarse al menos un rango.")

        page_count = len(reader.pages)
        outputs = []

        for index, raw_range in enumerate(ranges, start=1):
            start, end = int(raw_range[0]), int(raw_range[1])

            if start < 1 or end < 1 or start > end or end > page_count:
                raise ValueError(
                    f"Rango fuera de límites: {(start, end)}. "
                    f"El PDF tiene {page_count} páginas."
                )

            writer = PdfWriter()

            for page_number in range(start, end + 1):
                writer.add_page(reader.pages[page_number - 1])

            output = build_output_path(
                operation=f"split_{index:02d}_{start}_{end}",
                source_path=source,
                extension=".pdf",
                subdir="split",
                stem=output_stem,
            )

            with output.open("wb") as fh:
                writer.write(fh)

            outputs.append(
                {
                    "range": [start, end],
                    "output_path": str(output),
                    "output_filename": output.name,
                    "page_count": end - start + 1,
                    "size_bytes": output.stat().st_size,
                }
            )

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=outputs[0]["output_path"],
            metadata={
                "source_page_count": page_count,
                "output_count": len(outputs),
                "outputs": outputs,
                "ranges": [[int(a), int(b)] for a, b in ranges],
                "mime_type": "application/pdf",
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def compress_pdf_basic(
    source_path: str | Path,
    output_stem: str | None = None,
) -> DocumentToolResult:
    operation = "pdf_compress_basic"

    try:
        _require_pypdf()
        source = assert_existing_file(source_path)
        reader = PdfReader(str(source))

        if reader.is_encrypted:
            raise ValueError(f"PDF cifrado/no soportado: {source.name}")

        writer = PdfWriter()

        for page in reader.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass
            writer.add_page(page)

        output = build_output_path(
            operation="compress",
            source_path=source,
            extension=".pdf",
            subdir="compressed",
            stem=output_stem,
        )

        with output.open("wb") as fh:
            writer.write(fh)

        original_size = source.stat().st_size
        output_size = output.stat().st_size
        reduction_bytes = original_size - output_size
        reduction_percent = round((reduction_bytes / original_size) * 100, 2) if original_size else 0

        warnings = []
        if output_size >= original_size:
            warnings.append(
                "La compresión básica no redujo el tamaño. "
                "Probablemente el PDF ya contiene imágenes comprimidas."
            )

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            warnings=warnings,
            metadata={
                "page_count": len(reader.pages),
                "original_size_bytes": original_size,
                "output_size_bytes": output_size,
                "reduction_bytes": reduction_bytes,
                "reduction_percent": reduction_percent,
                "mime_type": "application/pdf",
                "compression_mode": "pypdf_content_streams",
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )

def compress_pdf_rasterized(
    source_path: str | Path,
    *,
    dpi: int = 120,
    jpeg_quality: int = 55,
    grayscale: bool = False,
    output_stem: str | None = None,
) -> DocumentToolResult:
    """
    Compresión fuerte para PDFs escaneados.

    Estrategia:
    - Renderiza cada página a imagen.
    - Reconvierte a PDF con JPEG optimizado.
    - Reduce mucho en escaneos, pasaportes, padrones, contratos escaneados, etc.

    Aviso:
    - Puede perder texto seleccionable si el PDF tenía capa OCR.
    - Pensado para generar copia comprimida, nunca sustituye el original.
    """
    operation = "pdf_compress_rasterized"

    try:
        try:
            import fitz  # PyMuPDF
        except Exception as exc:
            raise RuntimeError("Falta dependencia PyMuPDF. Ejecuta pip install -r requirements.txt") from exc

        from PIL import Image
        from io import BytesIO

        source = assert_existing_file(source_path)

        dpi_i = int(dpi or 120)
        quality_i = int(jpeg_quality or 55)

        if dpi_i < 72 or dpi_i > 220:
            raise ValueError("dpi debe estar entre 72 y 220.")

        if quality_i < 25 or quality_i > 95:
            raise ValueError("jpeg_quality debe estar entre 25 y 95.")

        doc = fitz.open(str(source))

        if doc.is_encrypted:
            raise ValueError(f"PDF cifrado/no soportado: {source.name}")

        output = build_output_path(
            operation="compress_strong",
            source_path=source,
            extension=".pdf",
            subdir="compressed",
            stem=output_stem,
        )

        images = []
        zoom = dpi_i / 72
        matrix = fitz.Matrix(zoom, zoom)

        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            mode = "RGB"
            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)

            if grayscale:
                img = img.convert("L").convert("RGB")

            buffer = BytesIO()
            img.save(
                buffer,
                format="JPEG",
                quality=quality_i,
                optimize=True,
                progressive=True,
            )
            buffer.seek(0)

            page_image = Image.open(buffer).convert("RGB")
            images.append(page_image.copy())

            buffer.close()

        doc.close()

        if not images:
            raise ValueError("El PDF no contiene páginas.")

        first, rest = images[0], images[1:]
        first.save(
            output,
            save_all=True,
            append_images=rest,
            format="PDF",
            resolution=dpi_i,
        )

        original_size = source.stat().st_size
        output_size = output.stat().st_size
        reduction_bytes = original_size - output_size
        reduction_percent = round((reduction_bytes / original_size) * 100, 2) if original_size else 0

        warnings = []
        if output_size >= original_size:
            warnings.append(
                "La compresión fuerte no redujo el tamaño. "
                "Prueba menor DPI/calidad o revisa si el PDF ya está optimizado."
            )

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            warnings=warnings,
            metadata={
                "page_count": len(images),
                "original_size_bytes": original_size,
                "output_size_bytes": output_size,
                "reduction_bytes": reduction_bytes,
                "reduction_percent": reduction_percent,
                "mime_type": "application/pdf",
                "compression_mode": "rasterized_jpeg",
                "dpi": dpi_i,
                "jpeg_quality": quality_i,
                "grayscale": bool(grayscale),
                "ocr_text_layer_preserved": False,
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )

