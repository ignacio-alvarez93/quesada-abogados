"""Clasificación provider-neutral de revisiones Knowledge.

No realiza persistencia.

Compara dos observaciones canónicas de la misma identidad y determina
si estamos ante una pieza nueva, una observación idéntica, una revisión
de metadata/provenance o una revisión material del contenido.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json

from .items import KnowledgeItem


class KnowledgeRevisionStatus(str, Enum):
    NEW = "NEW"
    UNCHANGED = "UNCHANGED"
    METADATA_REVISED = "METADATA_REVISED"
    CONTENT_REVISED = "CONTENT_REVISED"


@dataclass(frozen=True, slots=True)
class KnowledgeRevisionDecision:
    status: KnowledgeRevisionStatus
    canonical_key: str

    previous_record_sha256: str | None
    current_record_sha256: str

    previous_content_sha256: str | None
    current_content_sha256: str

    previous_source_revision: str
    current_source_revision: str

    @property
    def content_changed(self) -> bool:
        return (
            self.previous_content_sha256 is not None
            and self.previous_content_sha256
            != self.current_content_sha256
        )

    @property
    def record_changed(self) -> bool:
        return (
            self.previous_record_sha256 is not None
            and self.previous_record_sha256
            != self.current_record_sha256
        )


def knowledge_record_sha256(
    item: KnowledgeItem,
) -> str:
    """Fingerprint determinista de toda la observación canónica.

    El fingerprint de registro incluye el hash del contenido, no duplica
    el texto completo, y captura además metadata/provenance.
    """

    if not isinstance(item, KnowledgeItem):
        raise TypeError(
            "knowledge_record_sha256 requiere KnowledgeItem"
        )

    payload = {
        "source_key": item.source_key,
        "external_id": item.external_id,
        "title": item.title,
        "item_kind": item.item_kind.value,
        "canonical_uri": item.canonical_uri,
        "source_revision": item.source_revision,
        "published_on": (
            item.published_on.isoformat()
            if item.published_on is not None
            else None
        ),
        "language": item.language,
        "metadata": list(item.metadata),
        "content_sha256": item.content_sha256,
    }

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    return sha256(
        serialized.encode("utf-8")
    ).hexdigest()


def classify_knowledge_revision(
    *,
    previous: KnowledgeItem | None,
    current: KnowledgeItem,
) -> KnowledgeRevisionDecision:
    """Clasifica una observación nueva contra la versión conocida."""

    if not isinstance(current, KnowledgeItem):
        raise TypeError(
            "current debe ser KnowledgeItem"
        )

    current_record_sha256 = (
        knowledge_record_sha256(current)
    )

    if previous is None:
        return KnowledgeRevisionDecision(
            status=KnowledgeRevisionStatus.NEW,
            canonical_key=current.canonical_key,
            previous_record_sha256=None,
            current_record_sha256=current_record_sha256,
            previous_content_sha256=None,
            current_content_sha256=current.content_sha256,
            previous_source_revision="",
            current_source_revision=current.source_revision,
        )

    if not isinstance(previous, KnowledgeItem):
        raise TypeError(
            "previous debe ser KnowledgeItem o None"
        )

    if (
        previous.source_identity
        != current.source_identity
    ):
        raise ValueError(
            "No se pueden comparar revisiones "
            "de identidades Knowledge distintas"
        )

    previous_record_sha256 = (
        knowledge_record_sha256(previous)
    )

    if (
        previous_record_sha256
        == current_record_sha256
    ):
        status = (
            KnowledgeRevisionStatus.UNCHANGED
        )

    elif (
        previous.content_sha256
        != current.content_sha256
    ):
        status = (
            KnowledgeRevisionStatus.CONTENT_REVISED
        )

    else:
        status = (
            KnowledgeRevisionStatus.METADATA_REVISED
        )

    return KnowledgeRevisionDecision(
        status=status,
        canonical_key=current.canonical_key,
        previous_record_sha256=previous_record_sha256,
        current_record_sha256=current_record_sha256,
        previous_content_sha256=previous.content_sha256,
        current_content_sha256=current.content_sha256,
        previous_source_revision=previous.source_revision,
        current_source_revision=current.source_revision,
    )
