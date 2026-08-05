"""
Resultado global normalizado de extracción textual documental.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .document_page_result import (
    DocumentPageResult,
    TEXT_SOURCE_NATIVE,
    TEXT_SOURCE_OCR,
)


STATUS_NATIVE_TEXT = "NATIVE_TEXT"
STATUS_PARTIAL_OCR_REQUIRED = (
    "PARTIAL_OCR_REQUIRED"
)
STATUS_OCR_REQUIRED = "OCR_REQUIRED"
STATUS_EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
STATUS_UNSUPPORTED = "UNSUPPORTED"
STATUS_ERROR = "ERROR"

VALID_DOCUMENT_STATUSES = {
    STATUS_NATIVE_TEXT,
    STATUS_PARTIAL_OCR_REQUIRED,
    STATUS_OCR_REQUIRED,
    STATUS_EMPTY_DOCUMENT,
    STATUS_UNSUPPORTED,
    STATUS_ERROR,
}


@dataclass(slots=True)
class DocumentTextResult:
    status: str
    source_path: str
    source_name: str
    source_suffix: str
    sha256: str = ""
    mime_type: str = ""
    pages: list[DocumentPageResult] = field(
        default_factory=list
    )
    warnings: list[str] = field(
        default_factory=list
    )
    errors: list[str] = field(
        default_factory=list
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self):
        self.status = str(
            self.status or ""
        ).strip().upper()

        if self.status not in VALID_DOCUMENT_STATUSES:
            raise ValueError(
                "Estado documental no soportado: "
                f"{self.status}"
            )

        self.source_path = str(
            self.source_path or ""
        )
        self.source_name = str(
            self.source_name
            or Path(
                self.source_path
            ).name
        )
        self.source_suffix = str(
            self.source_suffix
            or Path(
                self.source_path
            ).suffix
        ).lower()
        self.sha256 = str(
            self.sha256 or ""
        ).strip()
        self.mime_type = str(
            self.mime_type or ""
        ).strip()

        self.pages = [
            (
                page
                if isinstance(
                    page,
                    DocumentPageResult,
                )
                else DocumentPageResult(
                    **dict(page)
                )
            )
            for page in (
                self.pages or []
            )
        ]

        self.warnings = [
            str(item)
            for item in (
                self.warnings or []
            )
        ]
        self.errors = [
            str(item)
            for item in (
                self.errors or []
            )
        ]
        self.metadata = dict(
            self.metadata or {}
        )

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def native_text_pages(self) -> int:
        return sum(
            1
            for page in self.pages
            if page.text_source
            == TEXT_SOURCE_NATIVE
        )

    @property
    def ocr_text_pages(self) -> int:
        return sum(
            1
            for page in self.pages
            if page.text_source
            == TEXT_SOURCE_OCR
        )

    @property
    def pages_requiring_ocr(self) -> list[int]:
        return [
            page.page_number
            for page in self.pages
            if page.requires_ocr
        ]

    @property
    def requires_ocr(self) -> bool:
        return bool(
            self.pages_requiring_ocr
        )

    @property
    def text(self) -> str:
        return "\n\n".join(
            page.text.strip()
            for page in self.pages
            if page.text.strip()
        ).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_path": self.source_path,
            "source_name": self.source_name,
            "source_suffix": self.source_suffix,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
            "page_count": self.page_count,
            "native_text_pages": (
                self.native_text_pages
            ),
            "ocr_text_pages": (
                self.ocr_text_pages
            ),
            "pages_requiring_ocr": (
                self.pages_requiring_ocr
            ),
            "requires_ocr": self.requires_ocr,
            "text": self.text,
            "pages": [
                page.to_dict()
                for page in self.pages
            ],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }
