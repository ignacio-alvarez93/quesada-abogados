"""
Contrato transversal de motores OCR.

Los consumidores documentales no deben depender directamente
de Tesseract, Google Vision, Azure ni ningún proveedor concreto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class OcrEngineResult:
    text: str
    confidence: float
    engine_code: str
    engine_version: str = ""
    language: str = ""
    warnings: list[str] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self):
        self.text = str(self.text or "")
        self.confidence = float(
            self.confidence or 0.0
        )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence debe estar entre 0 y 1"
            )

        self.engine_code = str(
            self.engine_code or ""
        ).strip()

        if not self.engine_code:
            raise ValueError(
                "engine_code es obligatorio"
            )

        self.engine_version = str(
            self.engine_version or ""
        ).strip()
        self.language = str(
            self.language or ""
        ).strip()
        self.warnings = [
            str(item)
            for item in (self.warnings or [])
        ]
        self.metadata = dict(
            self.metadata or {}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "engine_code": self.engine_code,
            "engine_version": self.engine_version,
            "language": self.language,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


class OcrEngine(ABC):
    engine_code = "ABSTRACT"

    @abstractmethod
    def is_available(self) -> bool:
        """Indica si el motor puede ejecutarse."""

    @abstractmethod
    def get_version(self) -> str:
        """Devuelve la versión técnica del motor."""

    @abstractmethod
    def list_languages(self) -> list[str]:
        """Devuelve los idiomas disponibles."""

    @abstractmethod
    def extract_image_text(
        self,
        image_path: str | Path,
        *,
        language: str = "eng",
    ) -> OcrEngineResult:
        """Extrae texto de una imagen."""
