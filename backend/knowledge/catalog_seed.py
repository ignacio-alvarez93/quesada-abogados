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


# ============================================================
# EUROPEAN UNION CORE
# ============================================================

EU_CORE_KNOWLEDGE_CATALOG_SEED: tuple[
    KnowledgeCatalogEntry,
    ...,
] = (
    # --------------------------------------------------------
    # Constitutional / primary framework
    # --------------------------------------------------------
    build_knowledge_catalog_entry(
        source_key="EUR_LEX",
        external_id="12016M/TXT",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Tratado de la Unión Europea: "
            "marco constitucional esencial de la UE."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="EUR_LEX",
        external_id="12016E/TXT",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Tratado de Funcionamiento de la Unión Europea: "
            "base jurídica transversal, incluidos artículos "
            "77 a 80 sobre fronteras, asilo e inmigración."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="EUR_LEX",
        external_id="12016P/TXT",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Carta de los Derechos Fundamentales "
            "de la Unión Europea."
        ),
    ),

    # --------------------------------------------------------
    # Schengen / borders / visas
    #
    # Para normativa mutable se gobierna la identidad
    # EUR_LEX_CONSOLIDATED porque representa el estado
    # español vigente utilizable.
    # --------------------------------------------------------
    build_knowledge_catalog_entry(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id="32016R0399",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Código de fronteras Schengen: "
            "norma central sobre cruce de fronteras."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id="32009R0810",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Código de visados: "
            "norma central del régimen común de visados."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id="32017R2226",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=95,
        added_reason=(
            "Sistema de Entradas y Salidas (EES): "
            "infraestructura jurídica europea de fronteras."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id="32018R1240",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=95,
        added_reason=(
            "ETIAS: autorización europea de viaje "
            "relevante para fronteras y movilidad."
        ),
    ),

    # --------------------------------------------------------
    # Legal migration
    # --------------------------------------------------------
    build_knowledge_catalog_entry(
        source_key="EUR_LEX_CONSOLIDATED",
        external_id="32021L1883",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Directiva Tarjeta Azul UE: "
            "migración altamente cualificada."
        ),
    ),
    build_knowledge_catalog_entry(
        source_key="EUR_LEX",
        external_id="32024L1233",
        tier=KnowledgeCatalogTier.CORE,
        watch_updates=True,
        priority=100,
        added_reason=(
            "Directiva de Permiso Único refundida. "
            "Se gobierna el original porque actualmente "
            "no existe consolidación española utilizable "
            "para la revisión sector-0 observada."
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



def seed_eu_core_knowledge_catalog(
    repository: KnowledgeCatalogRepository,
) -> tuple[
    KnowledgeCatalogWriteResult,
    ...,
]:
    """Registra idempotentemente el núcleo jurídico europeo."""

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
        in EU_CORE_KNOWLEDGE_CATALOG_SEED
    )
