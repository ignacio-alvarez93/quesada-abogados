"""Registro canónico de fuentes conocidas por Knowledge."""

from __future__ import annotations

from .contracts import (
    KnowledgeAuthority,
    KnowledgeSourceDefinition,
    KnowledgeSourceKind,
)


BOE_SOURCE = KnowledgeSourceDefinition(
    key="BOE",
    provider="BOE",
    display_name="Boletín Oficial del Estado",
    source_kind=KnowledgeSourceKind.OFFICIAL_GAZETTE,
    authority=KnowledgeAuthority.OFFICIAL_PRIMARY,
)


BOE_CONSOLIDATED_SOURCE = KnowledgeSourceDefinition(
    key="BOE_CONSOLIDATED",
    provider="BOE",
    display_name="BOE Legislación Consolidada",
    source_kind=KnowledgeSourceKind.OFFICIAL_LEGISLATION,
    authority=KnowledgeAuthority.OFFICIAL_SECONDARY,
)


_SOURCES: dict[str, KnowledgeSourceDefinition] = {
    BOE_SOURCE.key: BOE_SOURCE,
    BOE_CONSOLIDATED_SOURCE.key: BOE_CONSOLIDATED_SOURCE,
}


def normalize_source_key(value: str) -> str:
    """Normaliza una clave suministrada por consumidores."""

    key = str(value or "").strip().upper()

    if not key:
        raise ValueError(
            "Knowledge source key no puede estar vacío"
        )

    return key


def get_knowledge_source(
    source_key: str,
) -> KnowledgeSourceDefinition:
    """Obtiene una fuente registrada."""

    key = normalize_source_key(
        source_key
    )

    try:
        return _SOURCES[key]
    except KeyError as exc:
        raise KeyError(
            f"Fuente Knowledge no registrada: {key}"
        ) from exc


def knowledge_source_exists(
    source_key: str,
) -> bool:
    """Indica si una fuente está registrada."""

    try:
        key = normalize_source_key(
            source_key
        )
    except ValueError:
        return False

    return key in _SOURCES


def list_knowledge_sources(
    *,
    enabled_only: bool = True,
) -> tuple[
    KnowledgeSourceDefinition,
    ...,
]:
    """Devuelve el registro en orden estable."""

    sources = sorted(
        _SOURCES.values(),
        key=lambda item: item.key,
    )

    if enabled_only:
        sources = [
            source
            for source in sources
            if source.enabled
        ]

    return tuple(
        sources
    )
