"""
Renderizado de documentos a imágenes para motores OCR.

Actualmente soporta páginas PDF mediante PyMuPDF.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path


try:
    import fitz
except Exception:  # pragma: no cover
    fitz = None


@dataclass(slots=True)
class RenderedDocumentPage:
    page_number: int
    image_path: str
    width: int
    height: int
    dpi: int

    def to_dict(self):
        return {
            "page_number": self.page_number,
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "dpi": self.dpi,
        }


class PdfPageRenderer:
    def __init__(
        self,
        *,
        dpi: int = 220,
        output_directory: str | Path | None = None,
    ):
        self.dpi = int(dpi)

        if self.dpi < 72:
            raise ValueError(
                "El DPI debe ser al menos 72"
            )

        self.output_directory = (
            Path(output_directory)
            if output_directory
            else None
        )

    def _require_engine(self):
        if fitz is None:
            raise RuntimeError(
                "No está disponible PyMuPDF"
            )

    def render_pages(
        self,
        pdf_path: str | Path,
        page_numbers: list[int],
    ) -> list[RenderedDocumentPage]:
        self._require_engine()

        path = Path(pdf_path)

        if not path.exists():
            raise FileNotFoundError(
                f"No existe el PDF: {path}"
            )

        if path.suffix.lower() != ".pdf":
            raise ValueError(
                "El renderizador solo admite PDF"
            )

        requested = sorted(
            set(
                int(number)
                for number in page_numbers
            )
        )

        if not requested:
            return []

        output_dir = (
            self.output_directory
            or Path(
                tempfile.mkdtemp(
                    prefix="quesada_ocr_"
                )
            )
        )
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        document = fitz.open(
            str(path)
        )

        try:
            invalid = [
                number
                for number in requested
                if (
                    number < 1
                    or number > document.page_count
                )
            ]

            if invalid:
                raise ValueError(
                    "Páginas fuera de rango: "
                    + ", ".join(
                        str(item)
                        for item in invalid
                    )
                )

            scale = self.dpi / 72.0
            matrix = fitz.Matrix(
                scale,
                scale,
            )

            rendered = []

            for page_number in requested:
                page = document.load_page(
                    page_number - 1
                )

                pixmap = page.get_pixmap(
                    matrix=matrix,
                    alpha=False,
                )

                output_path = (
                    output_dir
                    / (
                        f"{path.stem}_"
                        f"page_{page_number:04d}.png"
                    )
                )

                pixmap.save(
                    str(output_path)
                )

                rendered.append(
                    RenderedDocumentPage(
                        page_number=page_number,
                        image_path=str(
                            output_path
                        ),
                        width=pixmap.width,
                        height=pixmap.height,
                        dpi=self.dpi,
                    )
                )

            return rendered
        finally:
            document.close()
