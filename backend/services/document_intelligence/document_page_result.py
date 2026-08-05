"""
Resultado normalizado de extracción de texto de una página.

Este contrato no conoce expedientes, formularios ni tipos documentales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TEXT_SOURCE_NATIVE = "NATIVE"
TEXT_SOURCE_OCR = "OCR"
TEXT_SOURCE_NONE = "NONE"

VALID_TEXT_SOURCES = {
    TEXT_SOURCE_NATIVE,
    TEXT_SOURCE_OCR,
    TEXT_SOURCE_NONE,
}


@dataclass(slots=True)
class DocumentPageResult:
    page_number: int
    text: str = ""
    text_source: str = TEXT_SOURCE_NONE
    confidence: float = 0.0
    requires_ocr: bool = False
    rotation: int = 0
    language: str = ""
    warnings: list[str] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self):
        self.page_number = int(
            self.page_number
        )

        if self.page_number <= 0:
            raise ValueError(
                "page_number debe ser mayor que cero"
            )

        self.text = str(
            self.text or ""
        )

        self.text_source = str(
            self.text_source
            or TEXT_SOURCE_NONE
        ).strip().upper()

        if self.text_source not in VALID_TEXT_SOURCES:
            raise ValueError(
                "Origen de texto no soportado: "
                f"{self.text_source}"
            )

        self.confidence = float(
            self.confidence or 0.0
        )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence debe estar entre 0 y 1"
            )

        self.requires_ocr = bool(
            self.requires_ocr
        )
        self.rotation = int(
            self.rotation or 0
        )
        self.language = str(
            self.language or ""
        ).strip()

        self.warnings = [
            str(item)
            for item in (
                self.warnings or []
            )
        ]
        self.metadata = dict(
            self.metadata or {}
        )

    @property
    def text_length(self) -> int:
        return len(self.text)

    @property
    def has_text(self) -> bool:
        return bool(
            self.text.strip()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "text_source": self.text_source,
            "confidence": self.confidence,
            "requires_ocr": self.requires_ocr,
            "rotation": self.rotation,
            "language": self.language,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "text_length": self.text_length,
            "has_text": self.has_text,
        }
