"""
Motor OCR basado en el ejecutable de Tesseract.

Se invoca mediante subprocess y no depende de pytesseract,
pandas ni de bindings binarios adicionales.
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .ocr_engine import (
    OcrEngine,
    OcrEngineResult,
)


DEFAULT_WINDOWS_PATHS = [
    Path(
        r"C:\Program Files"
        r"\Tesseract-OCR"
        r"\tesseract.exe"
    ),
    Path(
        r"C:\Program Files (x86)"
        r"\Tesseract-OCR"
        r"\tesseract.exe"
    ),
]


def _read_tsv_confidence(
    tsv_path: str | Path,
) -> dict:
    path = Path(tsv_path)

    if not path.exists():
        return {
            "confidence": 0.0,
            "recognized_words": 0,
            "confidence_values": [],
        }

    confidence_values = []
    recognized_words = 0

    with path.open(
        "r",
        encoding="utf-8",
        errors="replace",
        newline="",
    ) as file_handle:
        reader = csv.DictReader(
            file_handle,
            delimiter="\t",
        )

        for row in reader:
            word = str(
                row.get("text") or ""
            ).strip()

            if not word:
                continue

            try:
                raw_confidence = float(
                    row.get("conf") or -1
                )
            except (TypeError, ValueError):
                continue

            if raw_confidence < 0:
                continue

            recognized_words += 1
            confidence_values.append(
                raw_confidence
            )

    if not confidence_values:
        return {
            "confidence": 0.0,
            "recognized_words": recognized_words,
            "confidence_values": [],
        }

    average = (
        sum(confidence_values)
        / len(confidence_values)
    )

    normalized = max(
        0.0,
        min(
            1.0,
            average / 100.0,
        ),
    )

    return {
        "confidence": normalized,
        "recognized_words": recognized_words,
        "confidence_values": confidence_values,
        "average_raw_confidence": average,
    }


class TesseractCliOcrEngine(OcrEngine):
    engine_code = "TESSERACT_CLI"

    def __init__(
        self,
        executable_path: str | Path | None = None,
        *,
        timeout_seconds: int = 120,
        page_segmentation_mode: int = 6,
    ):
        self.executable_path = (
            self._resolve_executable(
                executable_path
            )
        )
        self.timeout_seconds = int(
            timeout_seconds
        )
        self.page_segmentation_mode = int(
            page_segmentation_mode
        )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds debe ser positivo"
            )

    @staticmethod
    def _resolve_executable(
        configured_path,
    ) -> Path | None:
        candidates = []

        if configured_path:
            candidates.append(
                Path(configured_path)
            )

        environment_path = os.getenv(
            "TESSERACT_CMD"
        )

        if environment_path:
            candidates.append(
                Path(environment_path)
            )

        discovered = shutil.which(
            "tesseract"
        )

        if discovered:
            candidates.append(
                Path(discovered)
            )

        candidates.extend(
            DEFAULT_WINDOWS_PATHS
        )

        for candidate in candidates:
            try:
                if (
                    candidate.exists()
                    and candidate.is_file()
                ):
                    return candidate.resolve()
            except OSError:
                continue

        return None

    def is_available(self) -> bool:
        return bool(
            self.executable_path
            and self.executable_path.exists()
        )

    def _run(
        self,
        arguments: list[str],
    ) -> subprocess.CompletedProcess:
        if not self.is_available():
            raise RuntimeError(
                "No está disponible el ejecutable "
                "de Tesseract"
            )

        command = [
            str(self.executable_path),
            *arguments,
        ]

        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
            check=False,
        )

    def get_version(self) -> str:
        if not self.is_available():
            return ""

        result = self._run(
            ["--version"]
        )

        first_line = (
            result.stdout
            or result.stderr
            or ""
        ).splitlines()

        return (
            first_line[0].strip()
            if first_line
            else ""
        )

    def list_languages(self) -> list[str]:
        if not self.is_available():
            return []

        result = self._run(
            ["--list-langs"]
        )

        output = "\n".join(
            part
            for part in [
                result.stdout,
                result.stderr,
            ]
            if part
        )

        languages = []

        for line in output.splitlines():
            value = line.strip()

            if (
                not value
                or value.lower().startswith(
                    "list of available"
                )
            ):
                continue

            if re.fullmatch(
                r"[A-Za-z0-9_+-]+",
                value,
            ):
                languages.append(value)

        return sorted(set(languages))

    def extract_image_text(
        self,
        image_path: str | Path,
        *,
        language: str = "eng",
    ) -> OcrEngineResult:
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(
                f"No existe la imagen: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"La ruta no es un archivo: {path}"
            )

        requested_language = str(
            language or "eng"
        ).strip()

        available_languages = (
            self.list_languages()
        )

        language_parts = [
            item.strip()
            for item in requested_language.split("+")
            if item.strip()
        ]

        missing_languages = [
            item
            for item in language_parts
            if item not in available_languages
        ]

        if missing_languages:
            raise ValueError(
                "Idiomas OCR no instalados: "
                + ", ".join(missing_languages)
            )

        with tempfile.TemporaryDirectory() as temp:
            output_base = (
                Path(temp)
                / "ocr_result"
            )

            result = self._run(
                [
                    str(path),
                    str(output_base),
                    "-l",
                    requested_language,
                    "--psm",
                    str(
                        self.page_segmentation_mode
                    ),
                    "txt",
                    "tsv",
                ]
            )

            if result.returncode != 0:
                detail = (
                    result.stderr
                    or result.stdout
                    or "Error desconocido"
                ).strip()

                raise RuntimeError(
                    "Tesseract no pudo procesar "
                    f"la imagen: {detail}"
                )

            output_file = output_base.with_suffix(
                ".txt"
            )

            if not output_file.exists():
                raise RuntimeError(
                    "Tesseract no generó el archivo "
                    "de texto esperado"
                )

            text_result = output_file.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip()

            tsv_file = output_base.with_suffix(
                ".tsv"
            )

            confidence_data = (
                _read_tsv_confidence(
                    tsv_file
                )
            )

        warnings = []

        if not text_result:
            warnings.append(
                "Tesseract no detectó texto"
            )

        confidence = (
            confidence_data["confidence"]
            if text_result
            else 0.0
        )

        if (
            text_result
            and not confidence_data[
                "recognized_words"
            ]
        ):
            warnings.append(
                "No se pudo calcular confianza "
                "TSV para el texto reconocido"
            )

        return OcrEngineResult(
            text=text_result,
            confidence=confidence,
            engine_code=self.engine_code,
            engine_version=self.get_version(),
            language=requested_language,
            warnings=warnings,
            metadata={
                "page_segmentation_mode": (
                    self.page_segmentation_mode
                ),
                "available_languages": (
                    available_languages
                ),
                "confidence_source": (
                    "TESSERACT_TSV_WORD_AVERAGE"
                ),
                "recognized_words": (
                    confidence_data[
                        "recognized_words"
                    ]
                ),
                "average_raw_confidence": (
                    confidence_data.get(
                        "average_raw_confidence",
                        0.0,
                    )
                ),
            },
        )
