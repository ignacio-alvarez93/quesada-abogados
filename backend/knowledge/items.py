"""Modelo canónico de piezas de conocimiento.

No contiene persistencia, red, UI ni procesamiento IA.

Una pieza de conocimiento conserva una identidad externa estable,
su procedencia y una huella del contenido normalizado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from typing import Mapping

from .contracts import KnowledgeItemKind
from .source_registry import (
    get_knowledge_source,
    normalize_source_key,
)


def normalize_knowledge_text(value: str) -> str:
    """Normaliza texto para comparación y fingerprint estable."""

    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def compute_content_sha256(value: str) -> str:
    """Calcula SHA-256 sobre contenido textual normalizado."""

    normalized = normalize_knowledge_text(value)

    return sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def normalize_language(value: str) -> str:
    language = str(value or "").strip().lower()

    if not language:
        raise ValueError("Knowledge item language no puede estar vacío")

    return language


def normalize_metadata(
    metadata: Mapping[str, object] | None,
) -> tuple[tuple[str, str], ...]:
    """Convierte metadata sencilla en representación estable e inmutable."""

    if not metadata:
        return ()

    normalized: list[tuple[str, str]] = []

    for raw_key, raw_value in metadata.items():
        key = str(raw_key or "").strip()

        if not key:
            raise ValueError(
                "Knowledge item metadata contiene una clave vacía"
            )

        value = "" if raw_value is None else str(raw_value).strip()

        normalized.append((key, value))

    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    """Representación canónica e inmutable de conocimiento ingerido."""

    source_key: str
    external_id: str
    title: str
    item_kind: KnowledgeItemKind
    content_text: str

    canonical_uri: str = ""
    source_revision: str = ""
    published_on: date | None = None
    language: str = "es"
    metadata: tuple[tuple[str, str], ...] = ()

    content_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        source_key = normalize_source_key(self.source_key)

        # Valida además que la fuente exista en el registro canónico.
        get_knowledge_source(source_key)

        external_id = str(self.external_id or "").strip()
        title = str(self.title or "").strip()
        content_text = normalize_knowledge_text(self.content_text)
        canonical_uri = str(self.canonical_uri or "").strip()
        source_revision = str(
            self.source_revision or ""
        ).strip()
        language = normalize_language(self.language)

        if not external_id:
            raise ValueError(
                "Knowledge item external_id no puede estar vacío"
            )

        if not title:
            raise ValueError(
                "Knowledge item title no puede estar vacío"
            )

        if not content_text:
            raise ValueError(
                "Knowledge item content_text no puede estar vacío"
            )

        if not isinstance(self.item_kind, KnowledgeItemKind):
            raise TypeError(
                "Knowledge item item_kind debe ser KnowledgeItemKind"
            )

        metadata = normalize_metadata(dict(self.metadata))

        object.__setattr__(self, "source_key", source_key)
        object.__setattr__(self, "external_id", external_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "content_text", content_text)
        object.__setattr__(self, "canonical_uri", canonical_uri)
        object.__setattr__(
            self,
            "source_revision",
            source_revision,
        )
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(
            self,
            "content_sha256",
            compute_content_sha256(content_text),
        )

    @property
    def source_identity(self) -> tuple[str, str]:
        """Identidad natural estable dentro de Knowledge."""

        return self.source_key, self.external_id

    @property
    def canonical_key(self) -> str:
        """Clave legible y estable para diagnóstico e idempotencia."""

        return f"{self.source_key}:{self.external_id}"


def build_knowledge_item(
    *,
    source_key: str,
    external_id: str,
    title: str,
    item_kind: KnowledgeItemKind,
    content_text: str,
    canonical_uri: str = "",
    source_revision: str = "",
    published_on: date | None = None,
    language: str = "es",
    metadata: Mapping[str, object] | None = None,
) -> KnowledgeItem:
    """Factory pública que acepta metadata convencional."""

    return KnowledgeItem(
        source_key=source_key,
        external_id=external_id,
        title=title,
        item_kind=item_kind,
        content_text=content_text,
        canonical_uri=canonical_uri,
        source_revision=source_revision,
        published_on=published_on,
        language=language,
        metadata=normalize_metadata(metadata),
    )
