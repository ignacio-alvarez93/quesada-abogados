"""
Política configurable para decidir si una página requiere OCR.

No intenta identificar el tipo de documento.
Solo valora la suficiencia técnica del texto extraído.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentTextPolicy:
    minimum_characters: int = 20
    minimum_alphanumeric_characters: int = 10
    minimum_words: int = 3

    def __post_init__(self):
        if self.minimum_characters < 0:
            raise ValueError(
                "minimum_characters no puede "
                "ser negativo"
            )

        if (
            self.minimum_alphanumeric_characters
            < 0
        ):
            raise ValueError(
                "minimum_alphanumeric_characters "
                "no puede ser negativo"
            )

        if self.minimum_words < 0:
            raise ValueError(
                "minimum_words no puede ser negativo"
            )

    def analyze(self, text) -> dict:
        normalized = str(
            text or ""
        ).strip()

        compact = re.sub(
            r"\s+",
            " ",
            normalized,
        )

        alphanumeric_count = sum(
            1
            for char in compact
            if char.isalnum()
        )

        words = re.findall(
            r"\b[\wÁÉÍÓÚÜÑáéíóúüñ]+\b",
            compact,
            flags=re.UNICODE,
        )

        sufficient = (
            len(compact)
            >= self.minimum_characters
            and alphanumeric_count
            >= self.minimum_alphanumeric_characters
            and len(words)
            >= self.minimum_words
        )

        reasons = []

        if (
            len(compact)
            < self.minimum_characters
        ):
            reasons.append(
                "Texto demasiado corto"
            )

        if (
            alphanumeric_count
            < self.minimum_alphanumeric_characters
        ):
            reasons.append(
                "Contenido alfanumérico insuficiente"
            )

        if len(words) < self.minimum_words:
            reasons.append(
                "Número de palabras insuficiente"
            )

        return {
            "sufficient": sufficient,
            "text_length": len(compact),
            "alphanumeric_count": (
                alphanumeric_count
            ),
            "word_count": len(words),
            "reasons": reasons,
        }


DEFAULT_TEXT_POLICY = DocumentTextPolicy()
