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
