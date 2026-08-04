"""
Motor OCR basado en el ejecutable de Tesseract.

Se invoca mediante subprocess y no depende de pytesseract,
pandas ni de bindings binarios adicionales.
"""

from __future__ import annotations

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

            text = output_file.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip()

        warnings = []

        if not text:
            warnings.append(
                "Tesseract no detectó texto"
            )

        # La salida TXT de Tesseract no proporciona una
        # confianza global fiable. Se usa una estimación
        # conservadora que deberá mejorarse con TSV.
        confidence = 0.75 if text else 0.0

        return OcrEngineResult(
            text=text,
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
                    "HEURISTIC_TEXT_OUTPUT"
                ),
            },
        )
