from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.safe_file_service import assert_existing_file, build_output_path


SUPPORTED_WORD_SUFFIXES = {".docx", ".doc"}


def word_to_pdf(
    source_path: str | Path,
    *,
    output_stem: str | None = None,
) -> DocumentToolResult:
    """
    Convierte documentos Word a PDF generando copia.

    Estrategia:
    1) Microsoft Word vía docx2pdf, ideal en Windows si Word está instalado.
    2) Fallback LibreOffice/soffice si está disponible en PATH.

    Nunca modifica el original.
    """
    operation = "word_to_pdf"

    try:
        source = assert_existing_file(source_path)

        if source.suffix.lower() not in SUPPORTED_WORD_SUFFIXES:
            raise ValueError(f"Formato Word no soportado: {source.suffix}")

        output = build_output_path(
            operation="word_to_pdf",
            source_path=source,
            extension=".pdf",
            subdir="converted",
            stem=output_stem,
        )

        warnings: list[str] = []
        converter_used = None

        try:
            from docx2pdf import convert as docx2pdf_convert

            docx2pdf_convert(str(source), str(output))
            converter_used = "docx2pdf"
        except Exception as exc:
            warnings.append(f"docx2pdf no pudo convertir: {exc}")

            soffice = shutil.which("soffice") or shutil.which("libreoffice")

            if not soffice:
                raise RuntimeError(
                    "No se pudo convertir Word a PDF. "
                    "Instala Microsoft Word para docx2pdf o LibreOffice/soffice."
                ) from exc

            output_dir = output.parent
            cmd = [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(source),
            ]

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if proc.returncode != 0:
                raise RuntimeError(
                    "LibreOffice no pudo convertir el documento. "
                    f"stdout={proc.stdout} stderr={proc.stderr}"
                )

            generated = output_dir / f"{source.stem}.pdf"

            if not generated.exists():
                candidates = sorted(output_dir.glob(f"{source.stem}*.pdf"))
                if not candidates:
                    raise RuntimeError("LibreOffice terminó sin generar PDF.")
                generated = candidates[-1]

            if generated.resolve() != output.resolve():
                if output.exists():
                    output.unlink()
                generated.rename(output)

            converter_used = "libreoffice"

        if not output.exists():
            raise RuntimeError("La conversión terminó sin generar archivo PDF.")

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            warnings=warnings,
            metadata={
                "source_extension": source.suffix.lower(),
                "mime_type": "application/pdf",
                "converter": converter_used,
                "size_bytes": output.stat().st_size,
            },
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )
