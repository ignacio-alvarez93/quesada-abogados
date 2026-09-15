"""Seeds gobernados iniciales del catálogo Knowledge.

Este módulo NO ingiere contenido y NO realiza HTTP.
Solo declara identidades que el despacho considera estratégicas.
"""

from __future__ import annotations

from .catalog import (
    KnowledgeCatalogEntry,
    KnowledgeCatalogTier,
    build_knowledge_catalog_entry,
)
from .catalog_repository import (
    KnowledgeCatalogRepository,
    KnowledgeCatalogWriteResult,
)


CORE_KNOWLEDGE_CATALOG_SEED: tuple[
    KnowledgeCatalogEntry,
    ...,
] = (
    build_knowledge_catalog_entry(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2000-544",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Norma estructural de extranjería: "
            "Ley Orgánica 4/2000."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2024-24099",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Reglamento vigente de desarrollo "
            "de la Ley Orgánica 4/2000."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2015-10565",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Norma transversal de procedimiento "
            "administrativo común."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="BOE_CONSOLIDATED",
        external_id="BOE-A-2015-11724",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Norma transversal de Seguridad Social "
            "relevante para expedientes y autorizaciones."
        ),
    ),
)


def seed_core_knowledge_catalog(
    repository: KnowledgeCatalogRepository,
) -> tuple[
    KnowledgeCatalogWriteResult,
    ...,
]:
    """Registra de forma idempotente el primer núcleo jurídico."""

    if not isinstance(
        repository,
        KnowledgeCatalogRepository,
    ):
        raise TypeError(
            "repository debe implementar "
            "KnowledgeCatalogRepository"
        )

    return tuple(
        repository.upsert(
            entry
        )
        for entry
        in CORE_KNOWLEDGE_CATALOG_SEED
    )
